"""The agent loop, with a scripted fake LLM. No API key or database needed."""

from types import SimpleNamespace

from agent import agent as agent_mod
from agent import db


def _block(type_, **kw):
    return SimpleNamespace(type=type_, **kw)


def _response(*blocks):
    return SimpleNamespace(content=list(blocks), usage=SimpleNamespace(input_tokens=100, output_tokens=20))


class FakeClient:
    """Plays back scripted responses and records each request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        # snapshot: the agent keeps appending to the same messages list
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


class FakeCon:
    def close(self):
        pass


def _patch_db(monkeypatch, calls):
    monkeypatch.setattr(db, "describe_schema", lambda con: "main.orders (table): order_total DECIMAL")

    def fake_run_sql(con, sql, **kw):
        calls.append(sql)
        return db.QueryResult(sql=sql, columns=["total"], rows=[(671425.37,)])

    monkeypatch.setattr(db, "run_sql", fake_run_sql)


def test_query_then_submit(monkeypatch):
    calls = []
    _patch_db(monkeypatch, calls)
    client = FakeClient(
        [
            _response(
                _block("text", text="Let me sum the orders."),
                _block("tool_use", id="t1", name="run_sql", input={"sql": "select sum(order_total) from main.orders"}),
            ),
            _response(
                _block(
                    "tool_use",
                    id="t2",
                    name="submit_answer",
                    input={"answer": "$671,425.37", "numeric_value": 671425.37, "status": "answered"},
                )
            ),
        ]
    )
    trace = agent_mod.ask("What was revenue?", client=client, con=FakeCon())

    assert trace["end_reason"] == "submitted"
    assert trace["answer"]["numeric_value"] == 671425.37
    assert calls == ["select sum(order_total) from main.orders"]
    assert trace["sql_calls"] == 1
    assert trace["usage"]["input_tokens"] == 200
    # the tool result went back to the model as a user turn
    tool_result = client.requests[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "t1"
    assert "671425.37" in tool_result["content"]


def test_nudges_once_then_gives_up(monkeypatch):
    _patch_db(monkeypatch, [])
    client = FakeClient([_response(_block("text", text="Revenue is high.")), _response(_block("text", text="Done."))])
    trace = agent_mod.ask("What was revenue?", client=client, con=FakeCon())
    assert trace["end_reason"] == "no_answer"
    assert client.requests[1]["messages"][-1]["content"] == agent_mod.NUDGE


def test_last_turn_forces_submit(monkeypatch):
    _patch_db(monkeypatch, [])
    query = _response(_block("tool_use", id="q", name="run_sql", input={"sql": "select 1"}))
    submit = _response(_block("tool_use", id="s", name="submit_answer", input={"answer": "x", "status": "answered"}))
    client = FakeClient([query, query, submit])
    config = agent_mod.AgentConfig(model="test-model", max_turns=3)
    trace = agent_mod.ask("q", client=client, con=FakeCon(), config=config)
    assert trace["end_reason"] == "submitted"
    assert client.requests[-1]["tool_choice"] == {"type": "tool", "name": "submit_answer"}
    assert client.requests[0]["tool_choice"] == {"type": "auto"}
