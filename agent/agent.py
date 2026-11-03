"""Step 0 baseline agent: schema names + one read-only SQL tool.

Deliberately thin. It knows table and column names, nothing about what the
business means by "revenue", "new customer" or "last quarter". Later steps add
context; this file is the control group, so keep it boring.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import time
from dataclasses import dataclass, field
from typing import Any

from agent import db

SYSTEM_PROMPT = """You are a data analyst. You answer business questions about the company's data \
by querying its DuckDB warehouse with the run_sql tool.

Warehouse tables and views (schema.name (kind): columns):
{schema}

Use run_sql as many times as you need. When you are done, call submit_answer exactly once."""

RUN_SQL_TOOL = {
    "name": "run_sql",
    "description": (
        "Run one read-only SQL query (DuckDB dialect, SELECT or WITH only) against the "
        f"warehouse. Returns up to {db.MAX_ROWS} rows as CSV text, or an error message."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"sql": {"type": "string", "description": "A single SELECT or WITH query."}},
        "required": ["sql"],
    },
}

SUBMIT_ANSWER_TOOL = {
    "name": "submit_answer",
    "description": "Submit your final answer to the question. Call it once, at the end.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "The answer for the user: a number, a short list or one or two sentences.",
            },
            "numeric_value": {
                "type": "number",
                "description": "The headline number, if the answer is a single number. Omit otherwise.",
            },
            "unit": {"type": "string", "description": "Unit of numeric_value, e.g. USD, orders, customers."},
            "sql": {"type": "string", "description": "The final query that produced the answer."},
            "definition_used": {
                "type": "string",
                "description": "How you defined the metric, e.g. 'sum of order_total including tax'.",
            },
            "assumptions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Assumptions you made, e.g. about time ranges or ambiguous terms.",
            },
            "status": {
                "type": "string",
                "enum": ["answered", "needs_clarification", "cannot_answer"],
            },
        },
        "required": ["answer", "status"],
    },
}

TOOLS = [RUN_SQL_TOOL, SUBMIT_ANSWER_TOOL]
NUDGE = "Please call submit_answer with your final answer now."


@dataclass
class AgentConfig:
    model: str = field(default_factory=lambda: os.environ.get("AGENT_MODEL", "claude-sonnet-5-5"))
    max_turns: int = 12
    max_tokens: int = 4096
    temperature: float = 0.0


def build_system_prompt(con) -> str:
    return SYSTEM_PROMPT.format(schema=db.describe_schema(con))


def ask(question: str, *, client=None, con=None, config: AgentConfig | None = None) -> dict[str, Any]:
    """Answer one question. Returns a trace dict; trace["answer"] holds the submitted answer."""
    config = config or AgentConfig()
    if client is None:
        import anthropic

        client = anthropic.Anthropic()
    own_con = con is None
    con = con or db.connect()

    system = build_system_prompt(con)
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
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
    }
    started = time.perf_counter()
    nudged = False

    try:
        for turn in range(config.max_turns):
            last_turn = turn == config.max_turns - 1
            response = client.messages.create(
                model=config.model,
                max_tokens=config.max_tokens,
                temperature=config.temperature,
                system=system,
                messages=messages,
                tools=TOOLS,
                tool_choice={"type": "tool", "name": "submit_answer"} if last_turn else {"type": "auto"},
            )
            trace["usage"]["input_tokens"] += response.usage.input_tokens
            trace["usage"]["output_tokens"] += response.usage.output_tokens
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    trace["steps"].append({"turn": turn, "type": "text", "text": block.text})
                elif block.type == "tool_use" and block.name == "submit_answer":
                    trace["answer"] = dict(block.input)
                    trace["end_reason"] = "submitted"
                    return trace
                elif block.type == "tool_use" and block.name == "run_sql":
                    result = db.run_sql(con, block.input.get("sql", ""))
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
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result.to_text(),
                            "is_error": result.error is not None,
                        }
                    )
                elif block.type == "tool_use":
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Unknown tool {block.name}.",
                            "is_error": True,
                        }
                    )

            if tool_results:
                messages.append({"role": "user", "content": tool_results})
            elif not nudged:
                # The model stopped talking without submitting; ask once.
                messages.append({"role": "user", "content": NUDGE})
                nudged = True
            else:
                trace["end_reason"] = "no_answer"
                return trace

        trace["end_reason"] = "max_turns"
        return trace
    finally:
        trace["latency_ms"] = int((time.perf_counter() - started) * 1000)
        trace["sql_calls"] = sum(1 for s in trace["steps"] if s["type"] == "sql")
        if own_con:
            con.close()
