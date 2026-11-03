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

from google import genai
from google.genai import types

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
    "parameters_json_schema": {
        "type": "object",
        "properties": {"sql": {"type": "string", "description": "A single SELECT or WITH query."}},
        "required": ["sql"],
    },
}

SUBMIT_ANSWER_TOOL = {
    "name": "submit_answer",
    "description": "Submit your final answer to the question. Call it once, at the end.",
    "parameters_json_schema": {
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

TOOLS = [types.Tool(function_declarations=[RUN_SQL_TOOL, SUBMIT_ANSWER_TOOL])]
NUDGE = "Please call submit_answer with your final answer now."


@dataclass
class AgentConfig:
    model: str = field(default_factory=lambda: os.environ.get("AGENT_MODEL", "models/gemini-3.5-flash-lite"))
    max_turns: int = 12
    max_tokens: int = 4096
    temperature: float = 0.0


def build_system_prompt(con) -> str:
    return SYSTEM_PROMPT.format(schema=db.describe_schema(con))


def _generation_config(system: str, config: AgentConfig, *, force_submit: bool) -> types.GenerateContentConfig:
    """Model settings for one turn. force_submit makes submit_answer the only callable tool."""
    calling = (
        types.FunctionCallingConfig(mode="ANY", allowed_function_names=["submit_answer"])
        if force_submit
        else types.FunctionCallingConfig(mode="AUTO")
    )
    return types.GenerateContentConfig(
        system_instruction=system,
        temperature=config.temperature,
        max_output_tokens=config.max_tokens,
        tools=TOOLS,
        tool_config=types.ToolConfig(function_calling_config=calling),
    )


def _tool_response(call: types.FunctionCall, *, result: str | None = None, error: str | None = None) -> types.Part:
    """A function call's reply. Gemini has no is_error flag: an "error" key marks a failure."""
    payload = {"error": error} if error is not None else {"output": result}
    return types.Part(function_response=types.FunctionResponse(id=call.id, name=call.name, response=payload))


def ask(question: str, *, client=None, con=None, config: AgentConfig | None = None) -> dict[str, Any]:
    """Answer one question. Returns a trace dict; trace["answer"] holds the submitted answer."""
    config = config or AgentConfig()
    if client is None:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    own_con = con is None
    con = con or db.connect()

    system = build_system_prompt(con)
    contents = [types.UserContent(parts=[types.Part(text=question)])]
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
            response = client.models.generate_content(
                model=config.model,
                contents=contents,
                config=_generation_config(system, config, force_submit=last_turn),
            )
            usage = response.usage_metadata
            trace["usage"]["input_tokens"] += usage.prompt_token_count or 0
            # Thinking tokens are billed as output but reported separately.
            trace["usage"]["output_tokens"] += (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)

            # A blocked or empty reply has no content: treat it as "stopped without submitting".
            content = response.candidates[0].content if response.candidates else None
            parts = (content.parts or []) if content else []
            if content:
                # Send the model's turn back unchanged: it carries Gemini's thought signatures.
                contents.append(content)

            tool_results = []
            for part in parts:
                call = part.function_call
                if part.text and part.text.strip() and not part.thought:
                    trace["steps"].append({"turn": turn, "type": "text", "text": part.text})
                elif call and call.name == "submit_answer":
                    trace["answer"] = dict(call.args or {})
                    trace["end_reason"] = "submitted"
                    return trace
                elif call and call.name == "run_sql":
                    result = db.run_sql(con, (call.args or {}).get("sql", ""))
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
                    if result.error is not None:
                        tool_results.append(_tool_response(call, error=result.to_text()))
                    else:
                        tool_results.append(_tool_response(call, result=result.to_text()))
                elif call:
                    tool_results.append(_tool_response(call, error=f"Unknown tool {call.name}."))

            if tool_results:
                contents.append(types.UserContent(parts=tool_results))
            elif not nudged:
                # The model stopped talking without submitting; ask once.
                contents.append(types.UserContent(parts=[types.Part(text=NUDGE)]))
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
