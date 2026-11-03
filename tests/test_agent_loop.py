"""The agent loop, with a scripted fake LLM. No API key or database needed."""

import json
from types import SimpleNamespace as NS

from agent import agent as agent_mod
from agent import db


def _call(name, id_="c", **args):
    return NS(id=id_, function=NS(name=name, arguments=json.dumps(args)))


def _response(*calls, text=None, tokens=(100, 25)):
    msg = NS(content=text, tool_calls=list(calls) or None)
    return NS(choices=[NS(message=msg)], usage=NS(prompt_tokens=tokens[0], completion_tokens=tokens[1]))


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


def test_query_then_submit(monkeypatch):
    calls = []
    _patch_db(monkeypatch, calls)
    client = FakeClient(
        [
            _response(_call("run_sql", "t1", sql="select sum(order_total) from main.orders"), text="Let me sum."),
            _response(_call("submit_answer", "t2", answer="$671,425.37", numeric_value=671425.37, status="answered")),
        ]
    )
    trace = agent_mod.ask("What was revenue?", client=client, con=FakeCon())

    assert trace["end_reason"] == "submitted"
    assert trace["answer"]["numeric_value"] == 671425.37
    assert calls == ["select sum(order_total) from main.orders"]
    assert trace["sql_calls"] == 1
    assert trace["usage"] == {"input_tokens": 200, "output_tokens": 50}
    # the system prompt leads, and the tool result went back keyed to the call id
    first = client.requests[0]["messages"]
    assert first[0]["role"] == "system" and first[1] == {"role": "user", "content": "What was revenue?"}
    reply = client.requests[1]["messages"][-1]
    assert reply["role"] == "tool" and reply["tool_call_id"] == "t1" and "671425.37" in reply["content"]
    assert client.requests[1]["messages"][-2]["tool_calls"][0]["id"] == "t1"


def test_sql_error_goes_back_as_error(monkeypatch):
    _patch_db(monkeypatch, [], error="Binder Error: no such column")
    client = FakeClient(
        [
            _response(_call("run_sql", sql="select nope from main.orders")),
            _response(_call("submit_answer", answer="x", status="cannot_answer")),
        ]
    )
    agent_mod.ask("q", client=client, con=FakeCon())
    content = client.requests[1]["messages"][-1]["content"]
    assert content.startswith("ERROR:") and "Binder Error" in content


def test_unknown_tool_goes_back_as_error(monkeypatch):
    _patch_db(monkeypatch, [])
    client = FakeClient(
        [_response(_call("drop_table")), _response(_call("submit_answer", answer="x", status="answered"))]
    )
    agent_mod.ask("q", client=client, con=FakeCon())
    assert client.requests[1]["messages"][-1]["content"] == "ERROR: Unknown tool drop_table."


def test_bad_json_arguments_go_back_as_error(monkeypatch):
    _patch_db(monkeypatch, [])
    bad = NS(id="b", function=NS(name="run_sql", arguments="{not json"))
    client = FakeClient([_response(bad), _response(_call("submit_answer", answer="x", status="answered"))])
    trace = agent_mod.ask("q", client=client, con=FakeCon())
    assert trace["end_reason"] == "submitted"
    assert "not valid JSON" in client.requests[1]["messages"][-1]["content"]


def test_nudges_once_then_gives_up(monkeypatch):
    _patch_db(monkeypatch, [])
    client = FakeClient([_response(text="Revenue is high."), _response(text="Done.")])
    trace = agent_mod.ask("What was revenue?", client=client, con=FakeCon())
    assert trace["end_reason"] == "no_answer"
    assert client.requests[1]["messages"][-1] == {"role": "user", "content": agent_mod.NUDGE}


def test_empty_response_is_treated_as_no_answer(monkeypatch):
    _patch_db(monkeypatch, [])
    empty = NS(choices=[], usage=None)
    client = FakeClient([empty, empty])
    trace = agent_mod.ask("q", client=client, con=FakeCon())
    assert trace["end_reason"] == "no_answer"


def test_last_turn_forces_submit(monkeypatch):
    _patch_db(monkeypatch, [])
    query = _response(_call("run_sql", sql="select 1"))
    submit = _response(_call("submit_answer", answer="x", status="answered"))
    client = FakeClient([query, query, submit])
    config = agent_mod.AgentConfig(model="test-model", max_turns=3)
    trace = agent_mod.ask("q", client=client, con=FakeCon(), config=config)
    assert trace["end_reason"] == "submitted"
    assert client.requests[-1]["tool_choice"] == {"type": "function", "function": {"name": "submit_answer"}}
    assert client.requests[0]["tool_choice"] == "auto"
