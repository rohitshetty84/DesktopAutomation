"""
studio/server.py — local web dashboard for the Adaptive SAP test engine.

FastAPI app serving a single-page dashboard (static/index.html): browse YAML
tests, trigger a run, watch step-by-step progress live via SSE, and browse run
history (persisted by engine/run_store.py, alongside the existing static HTML
reports from engine/report.py).

Each triggered run launches its own fresh SAP GUI session (sapshcut.exe + SSO,
via SapSession.launch()) and closes it when the run finishes — no state carried
over from a previous run. SAP GUI Scripting is not safe to drive from multiple
threads at once, so runs are serialized through a single-worker executor.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional

import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from desktoptest.engine import AdaptiveEngine, RunResult, load_dir, report, run_store  # noqa: E402
from desktoptest.model import LLMService  # noqa: E402
from desktoptest.sap import SapSession  # noqa: E402

# Without this, Python's logging only surfaces WARNING+ by default, so every
# logger.info() in the engine/sap layers (including the status-bar check below)
# would silently vanish when running via the dashboard instead of the CLI.
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("desktoptest.studio")

TESTS_DIR = ROOT / "tests"
REPORTS_DIR = ROOT / "reports"
RUNS_DIR = REPORTS_DIR / "runs"
CONFIG_PATH = ROOT / "config" / "models.yaml"
STATIC_DIR = Path(__file__).parent / "static"

_state: Dict[str, object] = {}  # llm, populated on startup — SAP is launched per run
_executor = ThreadPoolExecutor(max_workers=1)  # see module docstring: COM thread-affinity
_run_queues: Dict[str, "asyncio.Queue[dict]"] = {}
_active_run_id: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    _state["llm"] = LLMService.from_config(str(CONFIG_PATH))
    yield


app = FastAPI(title="SAP Test Studio", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


# ── tests ────────────────────────────────────────────────────────────────────
@app.get("/api/tests")
def list_tests():
    return [
        {"name": t.name, "intent": t.intent, "transaction": t.transaction,
         "expect": t.expect, "step_count": len(t.steps)}
        for t in load_dir(TESTS_DIR)
    ]


@app.get("/api/tests/{name}")
def get_test(name: str):
    for t in load_dir(TESTS_DIR):
        if t.name == name:
            return {
                "name": t.name, "intent": t.intent, "transaction": t.transaction,
                "expect": t.expect, "steps": [s.__dict__ for s in t.steps],
            }
    raise HTTPException(404, f"test {name!r} not found")


class NewTestBody(BaseModel):
    name: str
    intent: str
    transaction: str = ""
    expect: str = ""


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return (slug or "test")[:60]


def _find_test_file(name: str) -> Path:
    for p in sorted(TESTS_DIR.glob("*.y*ml")):
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if data.get("name", p.stem) == name:
            return p
    raise HTTPException(404, f"test {name!r} not found")


@app.post("/api/tests")
def create_test(body: NewTestBody):
    name = body.name.strip()
    intent = body.intent.strip()
    if not name or not intent:
        raise HTTPException(400, "name and intent are required")

    # name is free text from the browser — never use it as a path component
    # directly (path traversal). Slugify to a safe filename, then de-dupe.
    base = _slugify(name)
    path = TESTS_DIR / f"{base}.yaml"
    n = 2
    while path.exists():
        path = TESTS_DIR / f"{base}_{n}.yaml"
        n += 1

    # No `steps` written — this is an intent-only test, same as authoring one
    # by hand with just intent/expect. The planner generates steps from live
    # SAP on first run; self-heal keeps them working after that.
    data = {
        "name": name,
        "intent": intent,
        "transaction": body.transaction.strip(),
        "expect": body.expect.strip(),
    }
    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    logger.info("created test %r at %s", name, path)
    return {"name": name, "path": str(path)}


@app.put("/api/tests/{name}")
def update_test(name: str, body: NewTestBody):
    path = _find_test_file(name)
    new_name = body.name.strip()
    new_intent = body.intent.strip()
    if not new_name or not new_intent:
        raise HTTPException(400, "name and intent are required")

    # Re-read + only touch the 4 text fields — `steps` (if any) round-trips
    # untouched. Note: this rewrites the file via yaml.safe_dump, which does
    # NOT preserve hand-written comments in the original YAML (PyYAML can't
    # round-trip them) — only matters for files that get edited via this form.
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data["name"] = new_name
    data["intent"] = new_intent
    data["transaction"] = body.transaction.strip()
    data["expect"] = body.expect.strip()
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    logger.info("updated test %r at %s", new_name, path)
    return {"name": new_name, "path": str(path)}


# ── run history ──────────────────────────────────────────────────────────────
@app.get("/api/runs")
def list_runs():
    return run_store.list_runs(RUNS_DIR)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    record = run_store.load_run(RUNS_DIR, run_id)
    if record is None:
        raise HTTPException(404, f"run {run_id!r} not found")
    return record


@app.get("/api/runs/{run_id}/report")
def get_run_report(run_id: str):
    record = run_store.load_run(RUNS_DIR, run_id)
    path = record.get("report_html_path") if record else None
    if not path or not Path(path).is_file():
        raise HTTPException(404, "report not found")
    return FileResponse(path)


# ── triggering + live progress ──────────────────────────────────────────────
class TriggerBody(BaseModel):
    test_name: str


@app.post("/api/runs/trigger")
async def trigger_run(body: TriggerBody):
    global _active_run_id
    if _active_run_id is not None:
        raise HTTPException(409, f"run {_active_run_id!r} is already in progress")

    test = next((t for t in load_dir(TESTS_DIR) if t.name == body.test_name), None)
    if test is None:
        raise HTTPException(404, f"test {body.test_name!r} not found")

    run_id = uuid.uuid4().hex[:8]
    queue: "asyncio.Queue[dict]" = asyncio.Queue()
    _run_queues[run_id] = queue
    _active_run_id = run_id
    loop = asyncio.get_running_loop()

    def emit(evt: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, evt)

    def do_run() -> None:
        global _active_run_id
        started_at = datetime.now()
        sap = None
        try:
            emit({"type": "sap_launching"})
            sap = SapSession.launch()
            emit({"type": "sap_ready"})
            engine = AdaptiveEngine(_state["llm"], sap)  # type: ignore[arg-type]
            result = engine.run(test, on_event=emit)
            out = report.write_html(result, str(REPORTS_DIR))
            run_store.save_run(result, run_id=run_id, started_at=started_at,
                               finished_at=datetime.now(), out_dir=RUNS_DIR,
                               report_path=out, source="dashboard")
        except Exception as e:  # noqa: BLE001 — must still unblock the SSE client
            logger.exception("run %s failed", run_id)
            detail = str(e)
            # Persist a failure record too — otherwise a crash (e.g. SAP launch
            # timing out) leaves no trace in Run History, only this transient event.
            failed = RunResult(test=test, passed=False, verification=f"Run errored: {detail}")
            run_store.save_run(failed, run_id=run_id, started_at=started_at,
                               finished_at=datetime.now(), out_dir=RUNS_DIR,
                               report_path=None, source="dashboard")
            emit({"type": "error", "detail": detail})
        finally:
            if sap is not None:
                sap.close()
            emit({"type": "done"})
            _active_run_id = None

    loop.run_in_executor(_executor, do_run)
    return {"run_id": run_id, "stream_url": f"/api/runs/{run_id}/stream"}


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str):
    queue = _run_queues.get(run_id)

    async def event_gen():
        if queue is None:
            record = run_store.load_run(RUNS_DIR, run_id)
            evt = ({"type": "complete", "record": record} if record
                  else {"type": "error", "detail": "run not found"})
            yield f"data: {json.dumps(evt)}\n\n"
            return
        try:
            while True:
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=20)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(evt)}\n\n"
                # "done" (set in do_run's finally) is the true terminal event —
                # it's only enqueued after the report + run record are written,
                # unlike the engine's own "run_done", which fires mid-write.
                if evt.get("type") == "done":
                    break
        finally:
            _run_queues.pop(run_id, None)

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
