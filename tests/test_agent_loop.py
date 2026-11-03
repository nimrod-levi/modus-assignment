"""The agent loop, with a scripted fake LLM. No API key or database needed."""

from google.genai import types

from agent import agent as agent_mod
from agent import db


def _text(text):
    return types.Part(text=text)


def _call(name, id_=None, **args):
    return types.Part(function_call=types.FunctionCall(id=id_, name=name, args=args))


def _response(*parts):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=100, candidates_token_count=20, thoughts_token_count=5
        ),
    )


class FakeClient:
    """Plays back scripted responses and records each request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.models = self

    def generate_content(self, **kwargs):
        # snapshot: the agent keeps appending to the same contents list
        self.requests.append({**kwargs, "contents": list(kwargs["contents"])})
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


def _calling_config(request):
    return request["config"].tool_config.function_calling_config


def test_query_then_submit(monkeypatch):
    calls = []
    _patch_db(monkeypatch, calls)
    client = FakeClient(
        [
            _response(
                _text("Let me sum the orders."),
                _call("run_sql", "t1", sql="select sum(order_total) from main.orders"),
            ),
            _response(_call("submit_answer", "t2", answer="$671,425.37", numeric_value=671425.37, status="answered")),
        ]
    )
    trace = agent_mod.ask("What was revenue?", client=client, con=FakeCon())

    assert trace["end_reason"] == "submitted"
    assert trace["answer"]["numeric_value"] == 671425.37
    assert calls == ["select sum(order_total) from main.orders"]
    assert trace["sql_calls"] == 1
    assert trace["usage"] == {"input_tokens": 200, "output_tokens": 50}  # output includes thinking tokens
    # the tool result went back to the model as a user turn
    turn = client.requests[1]["contents"][-1]
    reply = turn.parts[0].function_response
    assert turn.role == "user" and reply.id == "t1" and reply.name == "run_sql"
    assert "671425.37" in reply.response["output"]


def test_sql_error_goes_back_as_error(monkeypatch):
    _patch_db(monkeypatch, [], error="Binder Error: no such column")
    client = FakeClient(
        [
            _response(_call("run_sql", sql="select nope from main.orders")),
            _response(_call("submit_answer", answer="x", status="cannot_answer")),
        ]
    )
    agent_mod.ask("q", client=client, con=FakeCon())
    reply = client.requests[1]["contents"][-1].parts[0].function_response
    assert "Binder Error" in reply.response["error"] and "output" not in reply.response


def test_unknown_tool_goes_back_as_error(monkeypatch):
    _patch_db(monkeypatch, [])
    client = FakeClient(
        [_response(_call("drop_table")), _response(_call("submit_answer", answer="x", status="answered"))]
    )
    agent_mod.ask("q", client=client, con=FakeCon())
    reply = client.requests[1]["contents"][-1].parts[0].function_response
    assert reply.response == {"error": "Unknown tool drop_table."}


def test_nudges_once_then_gives_up(monkeypatch):
    _patch_db(monkeypatch, [])
    client = FakeClient([_response(_text("Revenue is high.")), _response(_text("Done."))])
    trace = agent_mod.ask("What was revenue?", client=client, con=FakeCon())
    assert trace["end_reason"] == "no_answer"
    assert client.requests[1]["contents"][-1].parts[0].text == agent_mod.NUDGE


def test_empty_response_is_treated_as_no_answer(monkeypatch):
    _patch_db(monkeypatch, [])
    empty = types.GenerateContentResponse(
        candidates=[], usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=100)
    )
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
    forced = _calling_config(client.requests[-1])
    assert forced.mode == "ANY" and forced.allowed_function_names == ["submit_answer"]
    assert _calling_config(client.requests[0]).mode == "AUTO"
