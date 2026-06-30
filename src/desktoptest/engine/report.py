"""engine/report.py — render a RunResult to a self-contained HTML report."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from .schema import RunResult


def write_html(result: RunResult, out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"{result.test.name}_{ts}.html"

    rows = []
    for r in result.results:
        badge = "PASS" if r.ok else "FAIL"
        cls = "ok" if r.ok else "fail"
        heal = " 🔧 healed" if r.healed else ""
        rows.append(
            f"<tr class='{cls}'><td>{badge}{heal}</td>"
            f"<td>{html.escape(r.step.action)}</td>"
            f"<td><code>{html.escape(r.step.target)}</code></td>"
            f"<td>{html.escape(r.step.value)}</td>"
            f"<td>{html.escape(r.detail)}</td></tr>"
        )

    heal_log = "".join(
        f"<li><code>{html.escape(h.get('step',{}).get('target',''))}</code> → "
        f"<code>{html.escape(str(h.get('new_target')))}</code> — "
        f"{html.escape(h.get('reason',''))}</li>"
        for h in result.healing_log
    ) or "<li>none</li>"

    verdict = "PASSED" if result.passed else "FAILED"
    color = "#1a7f37" if result.passed else "#cf222e"

    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<title>{html.escape(result.test.name)} — {verdict}</title>
<style>
 body{{font:14px/1.5 -apple-system,Segoe UI,Arial;margin:2rem;color:#1f2328}}
 h1{{margin:0 0 .25rem}} .verdict{{color:{color};font-weight:700;font-size:1.2rem}}
 table{{border-collapse:collapse;width:100%;margin:1rem 0}}
 th,td{{border:1px solid #d0d7de;padding:.4rem .6rem;text-align:left;vertical-align:top}}
 th{{background:#f6f8fa}} tr.fail td{{background:#ffebe9}} tr.ok td:first-child{{color:#1a7f37}}
 code{{background:#f6f8fa;padding:.1rem .3rem;border-radius:4px}}
 .meta{{color:#57606a}}
</style></head><body>
<h1>{html.escape(result.test.name)}</h1>
<div class="verdict">{verdict}</div>
<p class="meta">Intent: {html.escape(result.test.intent)}<br>
Generated {datetime.now():%Y-%m-%d %H:%M:%S}</p>
<h3>Verification</h3><p>{html.escape(result.verification)}</p>
<h3>Steps</h3>
<table><tr><th>Result</th><th>Action</th><th>Target</th><th>Value</th><th>Detail</th></tr>
{''.join(rows)}</table>
<h3>Healing log</h3><ul>{heal_log}</ul>
</body></html>"""
    path.write_text(doc, encoding="utf-8")
    return path
