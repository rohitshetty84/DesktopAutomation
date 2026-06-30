"""
engine/run_store.py — persist RunResults as one JSON file per run.

Mirrors the dashboard's "run history" needs: a directory of <run_id>.json files,
globbed and sorted on read (no index file), independent of the static HTML report
that engine/report.py already writes. Used by both run.py (CLI) and studio/server.py
(dashboard), so run history is complete regardless of how a test was triggered.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schema import RunResult


def _step_dict(sr) -> dict:
    return {
        "action": sr.step.action, "target": sr.step.target,
        "value": sr.step.value, "note": sr.step.note,
        "ok": sr.ok, "detail": sr.detail,
        "healed": sr.healed, "new_target": sr.new_target,
    }


def save_run(result: RunResult, *, run_id: str, started_at: datetime, finished_at: datetime,
            out_dir: str | Path, report_path: Optional[Path] = None,
            source: str = "cli") -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "id": run_id,
        "test_name": result.test.name,
        "intent": result.test.intent,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "duration_s": round((finished_at - started_at).total_seconds(), 1),
        "passed": result.passed,
        "verification": result.verification,
        "steps": [_step_dict(sr) for sr in result.results],
        "healing_log": result.healing_log,
        "report_html_path": str(report_path) if report_path else None,
        "source": source,
    }
    path = out_dir / f"{run_id}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


def list_runs(out_dir: str | Path) -> List[Dict[str, Any]]:
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return []
    summaries = []
    for p in out_dir.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        summaries.append({
            "id": data.get("id", p.stem),
            "test_name": data.get("test_name", ""),
            "passed": data.get("passed", False),
            "started_at": data.get("started_at", ""),
            "duration_s": data.get("duration_s", 0),
            "source": data.get("source", "cli"),
        })
    summaries.sort(key=lambda r: r["started_at"], reverse=True)
    return summaries


def load_run(out_dir: str | Path, run_id: str) -> Optional[Dict[str, Any]]:
    path = Path(out_dir) / f"{run_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
