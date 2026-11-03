"""The agent loop, with a scripted fake LLM. No API key or database needed.

The loop: run_sql turns, then a separate final request with no tools and a strict JSON schema."""

import json
from types import SimpleNamespace as NS

from agent import agent as agent_mod
from agent import db


def _call(name, id_="c", **args):
    return NS(id=id_, function=NS(name=name, arguments=json.dumps(args)))


def _response(*calls, text=None, tokens=(100, 25), finish="stop"):
    msg = NS(content=text, tool_calls=list(calls) or None)
    return NS(choices=[NS(message=msg, finish_reason=finish)], usage=NS(prompt_tokens=tokens[0], completion_tokens=tokens[1]))


class FakeClient:
    """Plays back scripted responses and records each request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.chat = NS(completions=self)

    def create(self, **kwargs):
        # snapshot: the agent keeps appending to the same messages list
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


class FakeCon:
    def close(self):
        pass


def _patch_db(monkeypatch, calls, error=None):
    monkeypatch.setattr(db, "describe_schema", lambda con: "main.orders (table): order_total DECIMAL")

    def fake_run_sql(con, sql, **kw):
        calls.append(sql)
        return db.QueryResult(sql=sql, columns=["total"], rows=[(671425.37,)], error=error)

    monkeypatch.setattr(db, "run_sql", fake_run_sql)


ANSWER = json.dumps({"answer": "x", "numeric_value": 671425.37, "unit": "USD", "sql": None,
                     "definition_used": None, "assumptions": [], "status": "answered"})


def _text(content, tokens=(100, 25)):
    return _response(text=content, tokens=tokens)


def test_query_then_final_answer(monkeypatch):
    calls = []
    _patch_db(monkeypatch, calls)
    client = FakeClient(
        [
            _response(_call("run_sql", "t1", sql="select sum(order_total) from main.orders"), text="Let me sum."),
            _text("Done."),
            _text(ANSWER),
        ]
    )
    trace = agent_mod.ask("What was revenue?", client=client, con=FakeCon())

    assert trace["end_reason"] == "submitted" and trace["answer"]["numeric_value"] == 671425.37
    assert calls == ["select sum(order_total) from main.orders"] and trace["sql_calls"] == 1
    assert trace["usage"] == {"input_tokens": 300, "output_tokens": 75}
    first = client.requests[0]["messages"]
    assert first[0]["role"] == "system" and first[1] == {"role": "user", "content": "What was revenue?"}
    reply = client.requests[1]["messages"][-1]
    assert reply["role"] == "tool" and reply["tool_call_id"] == "t1" and "671425.37" in reply["content"]
    # exploration offers run_sql only; the final request has no tools and a strict schema
    assert [t["function"]["name"] for t in client.requests[0]["tools"]] == ["run_sql"]
    assert "tools" not in client.requests[2]
    assert client.requests[2]["response_format"]["json_schema"]["strict"] is True
    assert client.requests[2]["messages"][-1] == {"role": "user", "content": agent_mod.FINAL_REQUEST}


def test_sql_error_goes_back_as_error(monkeypatch):
    _patch_db(monkeypatch, [], error="Binder Error: no such column")
    client = FakeClient([_response(_call("run_sql", sql="select nope from main.orders")), _text("Done."), _text(ANSWER)])
    agent_mod.ask("q", client=client, con=FakeCon())
    content = client.requests[1]["messages"][-1]["content"]
    assert content.startswith("ERROR:") and "Binder Error" in content


def test_unknown_tool_goes_back_as_error(monkeypatch):
    _patch_db(monkeypatch, [])
    client = FakeClient([_response(_call("drop_table")), _text("Done."), _text(ANSWER)])
    agent_mod.ask("q", client=client, con=FakeCon())
    assert client.requests[1]["messages"][-1]["content"] == "ERROR: Unknown tool drop_table."


def test_bad_json_arguments_go_back_as_error(monkeypatch):
    _patch_db(monkeypatch, [])
    bad = NS(id="b", function=NS(name="run_sql", arguments="{not json"))
    client = FakeClient([_response(bad), _text("Done."), _text(ANSWER)])
    trace = agent_mod.ask("q", client=client, con=FakeCon())
    assert trace["end_reason"] == "submitted"
    assert "not valid JSON" in client.requests[1]["messages"][-1]["content"]


def test_turn_limit_goes_straight_to_final_answer(monkeypatch):
    _patch_db(monkeypatch, [])
    query = _response(_call("run_sql", sql="select 1"))
    client = FakeClient([query, query, _text(ANSWER)])
    config = agent_mod.AgentConfig(model="test-model", max_turns=3)
    trace = agent_mod.ask("q", client=client, con=FakeCon(), config=config)
    assert trace["end_reason"] == "submitted" and "tools" not in client.requests[-1]


def test_invalid_final_json_is_retried_then_capped(monkeypatch):
    _patch_db(monkeypatch, [])
    client = FakeClient([_text("Done.")] + [_text("not json")] * 10)
    config = agent_mod.AgentConfig(model="m", max_retries=2)
    trace = agent_mod.ask("q", client=client, con=FakeCon(), config=config)
    assert trace["end_reason"] == "api_error" and trace["answer"] is None
    assert trace["tool_rejections"] == 3


def test_invalid_final_json_then_valid(monkeypatch):
    _patch_db(monkeypatch, [])
    client = FakeClient([_text("Done."), _text("oops"), _text(ANSWER)])
    trace = agent_mod.ask("q", client=client, con=FakeCon())
    assert trace["end_reason"] == "submitted" and trace["tool_rejections"] == 1


class Rejected(Exception):
    """Looks like Groq's 400 tool_use_failed."""

    status_code = 400

    def __str__(self):
        return "Error code: 400 - tool_use_failed: Tool call validation failed: attempted to call tool 'json'"


class RejectingClient(FakeClient):
    """Like FakeClient, but an Exception in the script is raised instead of returned."""

    def create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_rejected_call_is_retried_with_feedback(monkeypatch):
    _patch_db(monkeypatch, [])
    client = RejectingClient([Rejected(), _text("Done."), _text(ANSWER)])
    trace = agent_mod.ask("q", client=client, con=FakeCon())
    assert trace["end_reason"] == "submitted" and trace["tool_rejections"] == 1
    assert any(s["type"] == "rejected_call" for s in trace["steps"])
    feedback = client.requests[1]["messages"][-1]
    assert feedback["role"] == "user" and "run_sql" in feedback["content"]


def test_rejections_are_capped(monkeypatch):
    _patch_db(monkeypatch, [])
    client = RejectingClient([Rejected() for _ in range(10)])
    config = agent_mod.AgentConfig(model="m", max_retries=3)
    trace = agent_mod.ask("q", client=client, con=FakeCon(), config=config)
    assert trace["end_reason"] == "api_error" and trace["answer"] is None
    assert trace["tool_rejections"] == 4 and len(client.requests) == 4


def test_other_api_errors_still_raise(monkeypatch):
    import pytest

    _patch_db(monkeypatch, [])
    err = Exception("boom")
    err.status_code = 500
    with pytest.raises(Exception, match="boom"):
        agent_mod.ask("q", client=RejectingClient([err]), con=FakeCon())


def test_finish_reason_is_recorded(monkeypatch):
    _patch_db(monkeypatch, [])
    trace = agent_mod.ask("q", client=FakeClient([_text("Done."), _text(ANSWER)]), con=FakeCon())
    assert [s["finish_reason"] for s in trace["steps"] if s["type"] == "finish"] == ["stop", "stop"]


def test_truncated_reply_is_retried_with_higher_limit(monkeypatch):
    _patch_db(monkeypatch, [])
    cut = _response(_call("run_sql", sql="select 1"), finish="length")
    client = FakeClient([cut, _text(None), _text(ANSWER)])
    trace = agent_mod.ask("q", client=client, con=FakeCon())
    assert trace["end_reason"] == "submitted" and trace["truncations"] == 1 and trace["tool_rejections"] == 0
    assert client.requests[1]["max_tokens"] == 2 * client.requests[0]["max_tokens"]
    # the cut-off reply is dropped: it never reaches the conversation, and its query is not run
    assert client.requests[1]["messages"] == client.requests[0]["messages"] and trace["sql_calls"] == 0


def test_truncation_is_capped_and_flagged(monkeypatch):
    _patch_db(monkeypatch, [])
    client = FakeClient([_response(text="thinking", finish="length") for _ in range(10)])
    config = agent_mod.AgentConfig(model="m", max_retries=2, max_tokens=100, max_tokens_cap=300)
    trace = agent_mod.ask("q", client=client, con=FakeCon(), config=config)
    assert trace["end_reason"] == "truncated" and trace["answer"] is None and trace["truncations"] == 3
    assert [r["max_tokens"] for r in client.requests] == [100, 200, 300]


def test_empty_choices_is_rejected_not_done(monkeypatch):
    _patch_db(monkeypatch, [])
    empty = NS(choices=[], usage=NS(prompt_tokens=1, completion_tokens=0))
    client = FakeClient([empty, _text("Done."), _text(ANSWER)])
    trace = agent_mod.ask("q", client=client, con=FakeCon())
    assert trace["end_reason"] == "submitted" and trace["tool_rejections"] == 1
    assert "empty" in client.requests[1]["messages"][-1]["content"]


def test_content_filter_is_rejected(monkeypatch):
    _patch_db(monkeypatch, [])
    client = FakeClient([_response(text="x", finish="content_filter"), _text("Done."), _text(ANSWER)])
    trace = agent_mod.ask("q", client=client, con=FakeCon())
    assert trace["tool_rejections"] == 1 and trace["end_reason"] == "submitted"


def test_stop_with_empty_content_is_a_legitimate_done(monkeypatch):
    _patch_db(monkeypatch, [])
    client = FakeClient([_text(None), _text(ANSWER)])
    trace = agent_mod.ask("q", client=client, con=FakeCon())
    assert trace["end_reason"] == "submitted" and trace["tool_rejections"] == 0 and trace["truncations"] == 0


def test_unknown_or_missing_finish_reason_counts_as_stop(monkeypatch):
    _patch_db(monkeypatch, [])
    client = FakeClient([_response(text="ok", finish="weird_value"), _response(text=ANSWER, finish=None)])
    trace = agent_mod.ask("q", client=client, con=FakeCon())
    assert trace["end_reason"] == "submitted" and trace["tool_rejections"] == 0
