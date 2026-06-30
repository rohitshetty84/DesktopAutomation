#!/usr/bin/env python3
"""
run.py — CLI runner for the Adaptive SAP test engine.

    python run.py tests/va01_create_order.yaml
    python run.py tests/                       # run every *.yaml in a folder
    python run.py tests/ --no-vision-heal      # text-only self-heal

Reads Azure + SAP settings from .env (see .env.example). On non-Windows hosts (or
with SAP_DRY_RUN=true) the SAP layer mocks actions so you can smoke-test wiring.
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path

# make src/ importable without installation
sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv  # noqa: E402

from desktoptest.engine import AdaptiveEngine, load_dir, load_test, report, run_store  # noqa: E402
from desktoptest.model import LLMService  # noqa: E402
from desktoptest.sap import SapSession  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
ROOT = Path(__file__).parent


def main() -> int:
    ap = argparse.ArgumentParser(description="Run AI-guided SAP GUI tests.")
    ap.add_argument("path", help="YAML test file or a folder of tests")
    ap.add_argument("--config", default=str(ROOT / "config" / "models.yaml"))
    ap.add_argument("--reports", default=str(ROOT / "reports"))
    ap.add_argument("--no-vision-heal", action="store_true",
                    help="disable screenshot-based self-heal (text-only)")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")

    llm = LLMService.from_config(args.config)

    p = Path(args.path)
    tests = load_dir(p) if p.is_dir() else [load_test(p)]
    if not tests:
        print(f"No tests found at {p}")
        return 2

    failures = 0
    for test in tests:
        print(f"\n=== {test.name} ===")
        # Fresh SAP GUI session per test (sapshcut.exe + SSO) — no leftover state
        # from a prior run carried into the next one.
        sap = SapSession.launch()
        engine = AdaptiveEngine(llm, sap, use_vision_heal=not args.no_vision_heal)
        started_at = datetime.now()
        result = engine.run(test)
        finished_at = datetime.now()
        sap.close()
        out = report.write_html(result, args.reports)
        run_store.save_run(result, run_id=uuid.uuid4().hex[:8], started_at=started_at,
                           finished_at=finished_at, out_dir=Path(args.reports) / "runs",
                           report_path=out, source="cli")
        status = "PASS" if result.passed else "FAIL"
        if not result.passed:
            failures += 1
        healed = sum(1 for r in result.results if r.healed)
        print(f"[{status}] {test.name} — {result.verification}")
        print(f"        steps={len(result.results)} healed={healed} report={out}")

    print(f"\n{len(tests) - failures}/{len(tests)} passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
