"""One-page web UI: ask a question, see the answer and every SQL step.

    python -m agent.web          # then open http://127.0.0.1:8000

Uses the same ask() and trace saving as the command line; no new dependencies.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from agent import db
from agent.__main__ import load_dotenv, save_trace
from agent.agent import ask

PAGE = """<!doctype html>
<meta charset="utf-8"><title>Data agent</title>
<style>
 body{font:15px/1.5 system-ui,sans-serif;max-width:820px;margin:32px auto;padding:0 16px;color:#222}
 form{display:flex;gap:8px} input{flex:1;padding:8px;font-size:15px} button{padding:8px 16px;font-size:15px}
 pre{background:#f4f4f4;padding:10px;overflow:auto;white-space:pre-wrap;border-radius:4px}
 .answer{font-size:18px;margin:16px 0 8px} .meta{color:#666;font-size:13px}
 dt{font-weight:600;margin-top:8px} dd{margin:0} .err{color:#b00020}
 details{margin:8px 0}
</style>
<h2>Data agent</h2>
<form id=f><input id=q placeholder="Ask a business question" autofocus><button id=b>Ask</button></form>
<div id=out></div>
<script>
const out = document.getElementById('out');
function el(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
function show(t) {
  out.replaceChildren();
  const a = t.answer || {};
  out.append(el('div', a.answer || '(no answer: ' + t.end_reason + ')', 'answer'));
  const dl = el('dl');
  for (const k of ['status', 'numeric_value', 'unit', 'definition_used', 'assumptions']) {
    const v = Array.isArray(a[k]) ? a[k].join('; ') : a[k];
    if (v !== undefined && v !== null && v !== '') { dl.append(el('dt', k), el('dd', String(v))); }
  }
  out.append(dl);
  if (a.sql) { out.append(el('dt', 'final sql'), el('pre', a.sql)); }
  const d = el('details'); d.open = true;
  d.append(el('summary', 'Steps (' + t.steps.length + ')'));
  for (const s of t.steps) {
    if (s.type === 'text') { d.append(el('pre', '[turn ' + s.turn + '] ' + s.text)); continue; }
    d.append(el('div', 'turn ' + s.turn + ' · ' + s.row_count + ' rows · ' + s.elapsed_ms + ' ms', 'meta'));
    d.append(el('pre', s.sql));
    d.append(s.error ? el('pre', s.error, 'err') : el('pre', s.preview));
  }
  out.append(d);
  const u = t.usage;
  out.append(el('div', t.model + ' · ' + t.provider + ' · ' + t.sql_calls + ' SQL calls · ' + u.input_tokens +
    ' in / ' + u.output_tokens + ' out tokens · ' + (t.latency_ms / 1000).toFixed(1) + 's · ' + t.end_reason, 'meta'));
}
document.getElementById('f').onsubmit = async (e) => {
  e.preventDefault();
  const b = document.getElementById('b'); b.disabled = true;
  out.replaceChildren(el('div', 'Thinking...', 'meta'));
  try {
    const r = await fetch('/ask', {method: 'POST', body: JSON.stringify({question: q.value})});
    const t = await r.json();
    if (t.error) { out.replaceChildren(el('pre', t.error, 'err')); } else { show(t); }
  } catch (err) { out.replaceChildren(el('pre', String(err), 'err')); }
  b.disabled = false;
};
</script>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/":
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        if self.path != "/ask":
            self._send(404, b"not found", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            question = json.loads(self.rfile.read(length))["question"].strip()
            if not question:
                raise ValueError("empty question")
            trace = ask(question)
            save_trace(trace)
            body = json.dumps(trace, default=str)
        except Exception as exc:  # show any failure on the page instead of a dead request
            body = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        self._send(200, body.encode(), "application/json")


def main() -> None:
    load_dotenv()
    port = int(os.environ.get("PORT", "8000"))
    print(f"http://127.0.0.1:{port}  (traces saved to {db.REPO_ROOT / 'runs'})")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
