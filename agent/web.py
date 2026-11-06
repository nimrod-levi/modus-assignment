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
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Data agent</title>
<style>
 :root{--bg:#fafafa;--card:#fff;--text:#1f2328;--muted:#656d76;--line:#e3e6ea;--accent:#4f46e5;--code:#f3f4f6;--err:#b42318;--ok:#067647;--warn:#b54708}
 @media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--text:#e6e8eb;--muted:#9aa3ad;--line:#2a2f3a;--accent:#818cf8;--code:#1e222b;--err:#f97066;--ok:#47cd89;--warn:#fdb022}}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
 main{max-width:860px;margin:0 auto;padding:40px 16px 64px}
 h1{font-size:20px;margin:0 0 20px;font-weight:600}
 form{display:flex;gap:8px;margin-bottom:24px}
 input{flex:1;padding:10px 14px;font:inherit;color:inherit;background:var(--card);border:1px solid var(--line);border-radius:8px}
 input:focus{outline:2px solid var(--accent);outline-offset:-1px}
 button{padding:10px 18px;font:inherit;font-weight:500;color:#fff;background:var(--accent);border:0;border-radius:8px;cursor:pointer}
 button:disabled{opacity:.5;cursor:default}
 .card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-bottom:16px}
 .answer{font-size:17px;margin:0}
 .label{font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:0 0 8px}
 .badge{display:inline-block;font-size:12px;font-weight:600;padding:2px 8px;border-radius:999px;border:1px solid var(--line);margin-bottom:10px}
 .badge.ok{color:var(--ok)} .badge.warn{color:var(--warn)} .badge.bad{color:var(--err)}
 dl{display:grid;grid-template-columns:max-content 1fr;gap:6px 16px;margin:12px 0 0}
 dt{color:var(--muted)} dd{margin:0}
 pre{background:var(--code);padding:10px 12px;margin:6px 0 0;overflow:auto;white-space:pre-wrap;border-radius:6px;font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
 .meta{color:var(--muted);font-size:13px} .err{color:var(--err)}
 .step{padding:12px 0;border-top:1px solid var(--line)} .step:first-of-type{border-top:0;padding-top:4px}
 summary{cursor:pointer;font-weight:600}
 .foot{text-align:center;margin-top:8px}
 .tbl{overflow:auto;max-height:480px}
 table{border-collapse:collapse;font-size:14px;width:100%}
 th,td{text-align:left;padding:5px 10px;border-bottom:1px solid var(--line)} th{color:var(--muted);font-weight:600;position:sticky;top:0;background:var(--card)}
 td.num{text-align:right;font-variant-numeric:tabular-nums}
</style>
<main>
<h1>Data agent</h1>
<form id=f><input id=q placeholder="Ask a business question" autofocus><button id=b>Ask</button></form>
<div id=out></div>
</main>
<script>
const out = document.getElementById('out');
function el(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
function card(label) {
  const c = el('div', undefined, 'card');
  if (label) c.append(el('p', label, 'label'));
  return c;
}
function show(t) {
  out.replaceChildren();
  const a = t.answer || {};

  const main = card();
  if (a.status) {
    const cls = {ok: 'ok', answered: 'ok'}[a.status] || (a.status.includes('refus') || a.status.includes('error') ? 'bad' : 'warn');
    main.append(el('span', a.status, 'badge ' + cls));
  }
  main.append(el('p', a.answer || '(no answer: ' + t.end_reason + ')', 'answer'));
  const dl = el('dl');
  for (const k of ['numeric_value', 'unit', 'definition_used', 'assumptions']) {
    const v = Array.isArray(a[k]) ? a[k].join('; ') : a[k];
    if (v !== undefined && v !== null && v !== '') { dl.append(el('dt', k.replace('_', ' ')), el('dd', String(v))); }
  }
  main.append(dl);
  out.append(main);

  if (a.table && a.table.rows) {
    const c = card('Table (' + a.table.rows.length + ' rows)');
    const tbl = el('table'), head = el('tr');
    for (const col of a.table.columns) head.append(el('th', col));
    tbl.append(head);
    for (const row of a.table.rows) {
      const tr = el('tr');
      for (const v of row) tr.append(el('td', v === null ? '' : String(v), typeof v === 'number' ? 'num' : undefined));
      tbl.append(tr);
    }
    const wrap = el('div', undefined, 'tbl');
    wrap.append(tbl);
    c.append(wrap);
    out.append(c);
  }

  if (a.sql) {
    const c = card('Final SQL');
    c.append(el('pre', a.sql));
    out.append(c);
  }

  const c = card('SQL steps (' + t.sql_calls + ' executed)');
  for (const s of t.steps) {
    const d = el('div', undefined, 'step');
    if (s.type === 'sql') {
      d.append(el('div', 'turn ' + s.turn + ' \u00b7 ' + s.row_count + ' rows \u00b7 ' + s.elapsed_ms + ' ms' + (s.truncated ? ' \u00b7 truncated' : ''), 'meta'));
      d.append(el('pre', s.sql));
      d.append(s.error ? el('pre', s.error, 'err') : el('pre', s.preview));
    } else if (s.type === 'repeated_sql') {
      d.append(el('div', 'turn ' + s.turn + ' \u00b7 same query repeated, not re-run', 'meta'));
      d.append(el('pre', s.sql));
    } else if (s.type === 'rejected_call') {
      d.append(el('div', 'turn ' + s.turn + ' \u00b7 rejected call', 'meta'));
      d.append(el('pre', s.reason, 'err'));
    } else {
      d.append(el('div', 'turn ' + s.turn + ' \u00b7 model note', 'meta'));
      d.append(el('pre', s.text));
    }
    c.append(d);
  }
  if (!t.steps.length) { c.append(el('div', 'No steps.', 'meta')); }
  out.append(c);

  const u = t.usage;
  out.append(el('div', t.model + ' \u00b7 ' + t.provider + ' \u00b7 ' + u.input_tokens +
    ' in / ' + u.output_tokens + ' out tokens \u00b7 ' + (t.latency_ms / 1000).toFixed(1) + 's \u00b7 ' + t.end_reason, 'meta foot'));
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
