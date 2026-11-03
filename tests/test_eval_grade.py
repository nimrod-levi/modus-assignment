"""Eval graders and runner plumbing. Uses a throwaway DuckDB file and a fake ask(); no API key."""

import csv

import duckdb
import types

import pytest

from agent import db
from eval import grade as g
from eval import run_eval as runner


@pytest.fixture()
def con(tmp_path):
    path = tmp_path / "t.duckdb"
    w = duckdb.connect(str(path))
    w.execute("create table t as select * from (values ('a', 10.5), ('b', 20.0), ('c', 3.0)) v(name, amount)")
    w.close()
    c = db.connect(path)
    yield c
    c.close()


def q(grader, gold_sql=None, qid="q1"):
    return {"id": qid, "category": "cat", "question": "?", "gold_sql": gold_sql, "grader": grader}


# --- gold ---------------------------------------------------------------------


def test_number_gold(con):
    assert g.compute_gold(con, q({"type": "number"}, "select sum(amount) from t")) == 33.5


def test_number_gold_must_be_single_value(con):
    with pytest.raises(ValueError, match="exactly one"):
        g.compute_gold(con, q({"type": "number"}, "select name, amount from t"))


def test_set_gold_and_exclusions(con):
    gold = g.compute_gold(
        con, q({"type": "set", "exclude_sql": "select name from t where amount < 5"}, "select name from t where amount > 5")
    )
    assert gold == {"items": ["a", "b"], "excluded": ["c"]}


def test_bad_gold_sql_fails_fast(con):
    with pytest.raises(ValueError, match="gold SQL failed"):
        g.compute_gold(con, q({"type": "number"}, "select * from missing_table"))


def test_status_has_no_gold(con):
    assert g.compute_gold(con, q({"type": "status", "status": "cannot_answer"})) is None


# --- grading ------------------------------------------------------------------


def ans(**kw):
    return {"status": "answered", **kw}


def test_number_within_tolerance():
    question = q({"type": "number", "unit": ["USD", "dollars"]})
    assert g.grade(question, 1000.0, ans(numeric_value=1000.5, unit="usd")).passed  # inside 0.1%
    assert not g.grade(question, 1000.0, ans(numeric_value=1010.0, unit="USD")).passed


def test_number_wrong_or_missing_unit_or_value():
    question = q({"type": "number", "unit": "USD"})
    assert not g.grade(question, 5.0, ans(numeric_value=5.0, unit="orders")).passed
    assert not g.grade(question, 5.0, ans(numeric_value=5.0)).passed
    assert not g.grade(question, 5.0, ans(answer="five")).passed


def test_unit_not_checked_when_unspecified():
    assert g.grade(q({"type": "number"}), 5.0, ans(numeric_value=5.0)).passed


def test_set_whole_word_match_and_exclusions():
    gold = {"items": ["Brooklyn", "Philadelphia"], "excluded": ["Chicago"]}
    question = q({"type": "set"})
    assert g.grade(question, gold, ans(answer="Philadelphia and brooklyn.")).passed
    assert not g.grade(question, gold, ans(answer="Only Brooklyn")).passed
    assert not g.grade(question, gold, ans(answer="Brooklyn, Philadelphia, Chicago")).passed
    # "ab" must not match inside "cabin"
    assert not g.grade(question, {"items": ["ab"], "excluded": []}, ans(answer="cabin")).passed


def test_status_checked_for_every_grader():
    assert not g.grade(q({"type": "number"}), 1.0, {"status": "cannot_answer", "numeric_value": 1.0}).passed
    unanswerable = q({"type": "status", "status": "cannot_answer"})
    assert g.grade(unanswerable, None, {"status": "cannot_answer"}).passed
    assert not g.grade(unanswerable, None, {"status": "answered"}).passed


def test_no_answer_fails():
    assert not g.grade(q({"type": "status"}), None, None).passed


# --- loader -------------------------------------------------------------------


def write_yaml(tmp_path, text):
    p = tmp_path / "qs.yaml"
    p.write_text(text)
    return p


def test_load_empty_template(tmp_path):
    assert runner.load_questions(write_yaml(tmp_path, "questions: []\n")) == []


def test_load_rejects_bad_files(tmp_path):
    base = "questions:\n  - id: a\n    category: c\n    question: x\n"
    with pytest.raises(ValueError, match="need gold_sql"):
        runner.load_questions(write_yaml(tmp_path, base + "    grader: {type: number}\n"))
    with pytest.raises(ValueError, match="grader.type"):
        runner.load_questions(write_yaml(tmp_path, base + "    grader: {type: vibes}\n"))
    dup = base + "    grader: {type: status}\n" + base[len("questions:\n"):] + "    grader: {type: status}\n"
    with pytest.raises(ValueError, match="duplicate"):
        runner.load_questions(write_yaml(tmp_path, dup))


# --- runner -------------------------------------------------------------------


def fake_trace(answer, tokens=(100, 20)):
    return {
        "answer": answer, "end_reason": "submitted", "model": "fake", "system_prompt_sha": "abc",
        "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1]}, "sql_calls": 2,
        "latency_ms": 5, "steps": [],
    }


def test_run_summarize_and_scoreboard(tmp_path):
    questions = [
        q({"type": "number"}, qid="n1") | {"category": "metrics"},
        q({"type": "status", "status": "cannot_answer"}, qid="s1") | {"category": "unanswerable"},
    ]
    calls = {"n": 0}

    def flaky(_text):  # n1 passes twice then errors once
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("503")
        return fake_trace(ans(numeric_value=7.0))

    records = runner.run_question(questions[0], 7.0, 3, flaky)
    records += runner.run_question(questions[1], None, 3, lambda _t: fake_trace({"status": "answered"}))
    assert [r["passed"] for r in records[:3]] == [True, True, False]
    assert records[2]["error"] is True

    s = runner.summarize(questions, records, 3)
    assert s["score"] == pytest.approx((2 / 3 + 0) / 2)
    assert s["pass_all"] == 0.0
    assert s["errors"] == 1
    assert s["per_category"] == {"metrics": pytest.approx(2 / 3), "unanswerable": 0.0}
    assert s["tokens_per_run"] == 120

    board = tmp_path / "scoreboard.csv"
    meta = {"timestamp": "t", "step": "x", "suite": "questions", "git_sha": "abc", "dirty": False,
            "model": "fake", "system_prompt_sha": "abc"}
    runner.append_scoreboard(meta, s, board)
    runner.append_scoreboard(meta, s, board)
    rows = list(csv.DictReader(board.open()))
    assert len(rows) == 2 and rows[0]["step"] == "x" and rows[0]["score"] == "0.333"


def test_status_list_accepts_any_listed_status():
    question = q({"type": "status", "status": ["needs_clarification", "cannot_answer"]})
    assert g.grade(question, None, {"status": "needs_clarification"}).passed
    assert g.grade(question, None, {"status": "cannot_answer"}).passed
    assert not g.grade(question, None, {"status": "answered"}).passed


def test_shipped_questions_are_valid_and_gold_runs():
    """Every question in eval/*.yaml loads, and its gold_sql runs (skips until `make db`)."""
    if not db.db_path().exists():
        pytest.skip("warehouse not built")
    con = db.connect()
    try:
        for path in (runner.DEFAULT_QUESTIONS, runner.EVAL_DIR / "holdout.yaml"):
            for question in runner.load_questions(path):
                g.compute_gold(con, question)
    finally:
        con.close()


def test_throttled_client_retries_429_then_succeeds():
    class RateLimited(Exception):
        status_code = 429

        def __str__(self):
            return "Rate limit reached. Please try again in 1m1.5s."

    class Inner:
        def __init__(self):
            self.calls = 0
            self.chat = types.SimpleNamespace(completions=self)

        def create(self, **kw):
            self.calls += 1
            if self.calls < 3:
                raise RateLimited()
            return "ok"

    sleeps = []
    inner = Inner()
    client = runner.ThrottledClient(inner, min_interval_s=0, sleep=sleeps.append)
    assert client.chat.completions.create(model="m") == "ok"
    assert inner.calls == 3 and sleeps == [62.5, 62.5]


def test_throttled_client_does_not_retry_other_errors():
    class Boom(Exception):
        status_code = 400

    class Inner:
        def __init__(self):
            self.chat = types.SimpleNamespace(completions=self)

        def create(self, **kw):
            raise Boom()

    with pytest.raises(Boom):
        runner.ThrottledClient(Inner(), min_interval_s=0, sleep=lambda s: None).create()


def test_retry_penalty_in_score():
    from eval import run_eval as runner

    trace = {"answer": {"answer": "5", "numeric_value": 5, "status": "answered"}, "usage": {"input_tokens": 1, "output_tokens": 1},
             "end_reason": "submitted", "model": "m", "system_prompt_sha": "s", "sql_calls": 0, "latency_ms": 1,
             "steps": [], "tool_rejections": 2}
    q = {"id": "n1", "category": "c", "question": "?", "grader": {"type": "number"}}
    recs = runner.run_question(q, 5, 1, lambda _t: trace)
    assert recs[0]["passed"] and recs[0]["credit"] == pytest.approx(0.8)
    s = runner.summarize([q], recs, 1)
    assert s["score"] == pytest.approx(0.8) and s["raw_score"] == 1.0 and s["rejections"] == 2


def test_throttled_client_gives_up_on_long_rate_limit_waits():
    from eval import run_eval as runner

    class Limited(Exception):
        status_code = 429

        def __str__(self):
            return "429 tokens per day. Please try again in 12m7.0s."

    inner = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(Limited()))))
    slept = []
    client = runner.ThrottledClient(inner, 0, sleep=slept.append)
    with pytest.raises(RuntimeError, match="rate limit"):
        client.create(model="m")
    assert slept == []
