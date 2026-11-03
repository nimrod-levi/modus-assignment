"""Step 0 baseline agent: schema names + one read-only SQL tool.

Deliberately thin. It knows table and column names, nothing about what the
business means by "revenue", "new customer" or "last quarter". Later steps add
context; this file is the control group, so keep it boring.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from agent import db

SYSTEM_PROMPT = """You are a data analyst. You answer business questions about the company's data \
by querying its DuckDB warehouse with the run_sql tool.

Warehouse tables and views (schema.name (kind): columns):
{schema}

Use run_sql as many times as you need to explore the data and compute numbers. When you have enough
information, stop calling tools and reply "Done." You will then be asked for the final answer."""

RUN_SQL_TOOL = {
    "name": "run_sql",
    "description": (
        "Use this to explore the data and to compute numbers. Runs one read-only SQL query "
        f"(DuckDB dialect, SELECT or WITH only) against the warehouse. Returns up to {db.MAX_ROWS} rows "
        "as CSV text, or an error message you can fix and retry. Not for giving the final answer."
    ),
    "parameters": {
        "type": "object",
        "properties": {"sql": {"type": "string", "description": "A single SELECT or WITH query."}},
        "required": ["sql"],
    },
}

# The final answer is not a tool call: it is a separate request with a strict JSON schema (see _final_answer).
# Strict mode needs every field listed in `required`, so optional ones are nullable.
ANSWER_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "final_answer",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "answer": {
                    "type": "string",
                    "description": "The answer for the user: a number, a short list or one or two sentences.",
                },
                "numeric_value": {
                    "type": ["number", "null"],
                    "description": "The headline number, if the answer is a single number. Null otherwise.",
                },
                "unit": {"type": ["string", "null"], "description": "Unit of numeric_value, e.g. USD, orders, customers."},
                "sql": {"type": ["string", "null"], "description": "The final query that produced the answer."},
                "definition_used": {
                    "type": ["string", "null"],
                    "description": "How you defined the metric, e.g. 'sum of order_total including tax'.",
                },
                "assumptions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Assumptions you made, e.g. about time ranges or ambiguous terms. Empty if none.",
                },
                "status": {
                    "type": "string",
                    "enum": ["answered", "needs_clarification", "cannot_answer"],
                    "description": (
                        "'answered' when the warehouse answers the question; 'needs_clarification' when the "
                        "question is ambiguous and you must ask the user something; 'cannot_answer' when the "
                        "warehouse cannot support the question."
                    ),
                },
            },
            "required": ["answer", "numeric_value", "unit", "sql", "definition_used", "assumptions", "status"],
            "additionalProperties": False,
        },
    },
}

TOOLS = [{"type": "function", "function": RUN_SQL_TOOL}]
FINAL_REQUEST = "Now give your final answer to the question."
REJECTED = (
    "Your last reply was rejected ({reason}). run_sql is the only tool; call it by that exact name, or reply in plain text."
)


@dataclass
class AgentConfig:
    model: str = field(default_factory=lambda: os.environ.get("AGENT_MODEL", "openai/gpt-oss-120b"))
    max_turns: int = 12
    max_tokens: int = 4096
    temperature: float = 0.0
    max_retries: int = 3  # rejected tool calls allowed per question; the next one ends the run


OPENROUTER_URL = "https://openrouter.ai/api/v1"
# OpenRouter routes one model slug across ~25 providers, and they differ (some ignore the strict json_schema final
# request and return empty content). So one provider is pinned, with no fallbacks: every run uses the same backend.
# require_parameters also refuses a provider that cannot honour `tools` / `response_format`. The serving provider
# is recorded in each trace ("provider"). Change it with OPENROUTER_PROVIDER.
# Reasoning effort is set explicitly too: left to the provider default, gpt-oss produced ~10x more tokens (slow, costly).
def provider_routing() -> dict[str, Any]:
    name = os.environ.get("OPENROUTER_PROVIDER", "Cerebras")
    effort = os.environ.get("OPENROUTER_REASONING_EFFORT", "medium")
    return {
        "provider": {"order": [name], "allow_fallbacks": False, "require_parameters": True},
        "reasoning": {"effort": effort},
    }


def make_client() -> OpenAI:
    """The only model client in the repo: OpenRouter via the OpenAI SDK. Needs OPENROUTER_API_KEY."""
    return OpenAI(base_url=OPENROUTER_URL, api_key=os.environ["OPENROUTER_API_KEY"])


def build_system_prompt(con) -> str:
    return SYSTEM_PROMPT.format(schema=db.describe_schema(con))


def _tool_message(call, text: str, *, is_error: bool = False) -> dict[str, Any]:
    """A tool call's reply. The chat API has no is_error flag: errors are prefixed with "ERROR:"."""
    return {"role": "tool", "tool_call_id": call.id, "content": f"ERROR: {text}" if is_error else text}


def _is_rejected_tool_call(exc: Exception) -> bool:
    """A provider may answer 400 `tool_use_failed` when the model's tool call is malformed (e.g. unknown tool name)."""
    return getattr(exc, "status_code", None) == 400 and "tool_use_failed" in str(exc)


def _rejection_reason(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    err = body.get("error", body) if isinstance(body, dict) else {}
    text = err.get("message") or str(exc)
    return text.strip().splitlines()[0][:200]


def _create(client, config, messages, trace, turn, **kwargs):
    """One model call. A rejected reply is sent back with feedback and retried, up to config.max_retries per
    question. Returns the response, or None when the cap is hit (trace["end_reason"] is then "api_error")."""
    while True:
        try:
            response = client.chat.completions.create(
                model=config.model,
                messages=messages,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                extra_body=provider_routing(),
                **kwargs,
            )
        except Exception as exc:
            if not _is_rejected_tool_call(exc):
                raise
            trace["tool_rejections"] += 1
            reason = _rejection_reason(exc)
            trace["steps"].append({"turn": turn, "type": "rejected_call", "reason": reason})
            if trace["tool_rejections"] > config.max_retries:
                trace["end_reason"] = "api_error"
                return None
            messages.append({"role": "user", "content": REJECTED.format(reason=reason)})
            continue
        trace["provider"] = getattr(response, "provider", None) or trace.get("provider")  # OpenRouter: who served it
        usage = response.usage
        trace["usage"]["input_tokens"] += (usage.prompt_tokens or 0) if usage else 0
        trace["usage"]["output_tokens"] += (usage.completion_tokens or 0) if usage else 0
        return response


def _final_answer(client, config, messages, trace, turn) -> None:
    """Ask for the final answer in a request with no tools and a strict JSON schema, then store it in the trace."""
    messages.append({"role": "user", "content": FINAL_REQUEST})
    for _ in range(config.max_retries + 1):
        response = _create(client, config, messages, trace, turn, response_format=ANSWER_FORMAT)
        if response is None:
            return
        msg = response.choices[0].message if response.choices else None
        try:
            answer = json.loads((msg.content or "") if msg else "")
            if not isinstance(answer, dict):
                raise ValueError("not a JSON object")
        except ValueError as exc:
            trace["tool_rejections"] += 1
            trace["steps"].append({"turn": turn, "type": "rejected_call", "reason": f"final answer was not valid JSON: {exc}"})
            if trace["tool_rejections"] > config.max_retries:
                break
            messages.append({"role": "assistant", "content": msg.content or "" if msg else ""})
            messages.append({"role": "user", "content": REJECTED.format(reason="the final answer must be a JSON object")})
            continue
        trace["answer"] = answer
        trace["end_reason"] = "submitted"
        return
    trace["end_reason"] = "api_error"


def ask(question: str, *, client=None, con=None, config: AgentConfig | None = None) -> dict[str, Any]:
    """Answer one question. Returns a trace dict; trace["answer"] holds the submitted answer."""
    config = config or AgentConfig()
    if client is None:
        client = make_client()
    own_con = con is None
    con = con or db.connect()

    system = build_system_prompt(con)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]
    trace: dict[str, Any] = {
        "question": question,
        "model": config.model,
        "temperature": config.temperature,
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "system_prompt_sha": hashlib.sha256(system.encode()).hexdigest()[:12],
        "steps": [],
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "answer": None,
        "end_reason": None,
        "tool_rejections": 0,
    }
    started = time.perf_counter()

    try:
        # Exploration turns: run_sql is the only tool. A reply with no tool call means "done"; the answer
        # is then requested separately. The last turn skips straight to the final answer.
        for turn in range(config.max_turns - 1):
            response = _create(client, config, messages, trace, turn, tools=TOOLS, tool_choice="auto")
            if response is None:
                return trace
            msg = response.choices[0].message if response.choices else None
            calls = (msg.tool_calls or []) if msg else []
            if msg and msg.content and msg.content.strip():
                trace["steps"].append({"turn": turn, "type": "text", "text": msg.content})
            if not calls:
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.function.name, "arguments": c.function.arguments},
                        }
                        for c in calls
                    ],
                }
            )
            for call in calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError as exc:
                    messages.append(_tool_message(call, f"Arguments were not valid JSON: {exc}", is_error=True))
                    continue
                if call.function.name != "run_sql":
                    messages.append(_tool_message(call, f"Unknown tool {call.function.name}.", is_error=True))
                    continue
                result = db.run_sql(con, args.get("sql", ""))
                trace["steps"].append(
                    {
                        "turn": turn,
                        "type": "sql",
                        "sql": result.sql,
                        "row_count": result.row_count,
                        "truncated": result.truncated,
                        "error": result.error,
                        "elapsed_ms": result.elapsed_ms,
                        "preview": result.to_text()[:1500],
                    }
                )
                messages.append(_tool_message(call, result.to_text(), is_error=result.error is not None))
        else:
            trace["steps"].append({"turn": config.max_turns - 1, "type": "text", "text": "turn limit reached"})
        _final_answer(client, config, messages, trace, config.max_turns - 1)
        return trace
    finally:
        trace["latency_ms"] = int((time.perf_counter() - started) * 1000)
        trace["sql_calls"] = sum(1 for s in trace["steps"] if s["type"] == "sql")
        if own_con:
            con.close()
