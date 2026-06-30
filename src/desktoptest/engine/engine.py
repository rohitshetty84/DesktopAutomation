"""
engine/engine.py — the Adaptive orchestrator.

The loop that ties everything together:

    PLAN (once, cached) ──► EXECUTE deterministically ──► VERIFY
                                   │
                                 step fails
                                   ▼
                            SELF-HEAL (AI) ──► retry ──► update cached plan

Design choices that match the "Adaptive" architecture you picked:
  * Deterministic-first: a cached plan runs with NO AI in the loop on the happy
    path — fast and cheap. The model is only invoked to plan once, to heal on
    failure, and to verify the outcome.
  * Self-healing: on a not-found element the healer inspects the live SAP tree,
    remaps the id, retries, and (optionally) rewrites the cached step so the next
    run is deterministic again.
"""

from __future__ import annotations

import json
import logging
from typing import Callable, List, Optional

from ..model import LLMService
from ..sap import SapSession
from . import ai
from .schema import RunResult, Step, StepResult, TestCase

logger = logging.getLogger("desktoptest.engine")

_MAX_HEAL_ATTEMPTS = 2

OnEvent = Optional[Callable[[dict], None]]


class AdaptiveEngine:
    def __init__(self, llm: LLMService, sap: SapSession, use_vision_heal: bool = True):
        self.llm = llm
        self.sap = sap
        self.use_vision_heal = use_vision_heal

    # ── public ───────────────────────────────────────────────────────────────
    def run(self, test: TestCase, on_event: OnEvent = None) -> RunResult:
        result = RunResult(test=test, passed=False)

        # 1) PLAN — use cached steps if the YAML provided them, else ask the model.
        steps = test.steps or self._plan(test)
        if not steps:
            result.verification = "No steps to execute (planner returned nothing)."
            self._emit(on_event, "run_done", passed=False)
            return result
        self._emit(on_event, "run_start", test_name=test.name, total_steps=len(steps))

        # 2) EXECUTE deterministically, with self-heal on failure.
        for index, step in enumerate(steps):
            self._emit(on_event, "step_start", index=index, step=step.__dict__)
            sr = self._execute_step(step, result, on_event, index)
            result.results.append(sr)
            self._emit(on_event, "step_result", index=index, ok=sr.ok, detail=sr.detail,
                       healed=sr.healed, new_target=sr.new_target)
            if not sr.ok:
                result.verification = f"Step failed and could not be healed: {sr.detail}"
                self._emit(on_event, "run_done", passed=False)
                return result

        # 3) VERIFY the business outcome.
        passed, reason, captured = ai.verify(
            self.llm, test.expect, self.sap.status_bar(), self._tree_json())
        result.passed = passed
        result.verification = reason
        if captured:
            result.verification += f"  | captured: {json.dumps(captured)}"
        self._emit(on_event, "verify_done", passed=passed, verification=result.verification)
        self._emit(on_event, "run_done", passed=passed)
        return result

    # ── internals ────────────────────────────────────────────────────────────
    def _emit(self, on_event: OnEvent, type: str, **kw) -> None:
        if on_event is None:
            return
        try:
            on_event({"type": type, **kw})
        except Exception as e:  # noqa: BLE001 — a broken callback must never fail a run
            logger.warning("on_event callback failed: %s", e)

    def _plan(self, test: TestCase) -> List[Step]:
        try:
            return ai.plan(self.llm, test.intent, test.transaction, self._tree_json())
        except Exception as e:  # noqa: BLE001
            logger.error("planning failed: %s", e)
            return []

    def _execute_step(self, step: Step, result: RunResult,
                      on_event: OnEvent, index: int) -> StepResult:
        try:
            self._apply(step)
            return StepResult(step=step, ok=True, detail="ok")
        except Exception as e:  # noqa: BLE001
            logger.warning("step failed (%s %s): %s", step.action, step.target, e)
            return self._heal_and_retry(step, str(e), result, on_event, index)

    def _heal_and_retry(self, step: Step, error: str, result: RunResult,
                        on_event: OnEvent, index: int) -> StepResult:
        for attempt in range(_MAX_HEAL_ATTEMPTS):
            self._emit(on_event, "heal_attempt", index=index, attempt=attempt + 1, error=error)
            image = self.sap.screenshot_b64() if self.use_vision_heal else None
            try:
                new_target, extra, reason = ai.heal(
                    self.llm, step, error, self._tree_json(), image)
            except Exception as e:  # noqa: BLE001
                logger.error("heal call failed: %s", e)
                break

            result.healing_log.append({
                "step": step.__dict__, "error": error,
                "new_target": new_target, "reason": reason, "attempt": attempt + 1,
            })

            try:
                for ex in extra:           # e.g. dismiss a popup first
                    self._apply(ex)
                if new_target:
                    step.target = new_target   # rewrite cached plan -> deterministic next time
                self._apply(step)
                return StepResult(step=step, ok=True, detail=f"healed: {reason}",
                                  healed=True, new_target=new_target)
            except Exception as e:  # noqa: BLE001
                error = str(e)
                logger.warning("retry after heal failed: %s", e)
        return StepResult(step=step, ok=False, detail=f"unhealable: {error}")

    def _apply(self, step: Step) -> None:
        """Map a Step onto a SapSession primitive."""
        a = step.action
        if a == "start_transaction":
            self.sap.start_transaction(step.target)
        elif a == "set_text":
            self.sap.set_text(step.target, step.value)
        elif a == "press":
            self.sap.press(step.target)
        elif a == "select":
            self.sap.select(step.target)
        elif a == "send_vkey":
            self.sap.send_vkey(int(step.target or "0"))
        elif a == "assert_status":
            bar = self.sap.status_bar()
            if step.value and step.value.lower() not in (bar.get("text", "") or "").lower():
                raise RuntimeError(
                    f"status assertion failed: expected {step.value!r} in {bar.get('text')!r}")
            return  # already inspected the status bar above — no need to re-check below
        else:
            raise RuntimeError(f"unknown action {a!r}")
        self._check_status()

    def _check_status(self) -> None:
        """Fail fast if SAP's own status bar reports an Error/Abort after an
        action, instead of silently continuing and only catching it later (if at
        all) via an unrelated assertion. Surfaces SAP's real message as the
        failure detail."""
        bar = self.sap.status_bar()
        msg_type = (bar.get("type") or "").strip().upper()
        logger.info("status check: type=%r text=%r", msg_type, bar.get("text"))
        if msg_type in ("E", "A"):
            text = bar.get("text") or "(no message text)"
            raise RuntimeError(f"SAP reported a {msg_type}-type message: {text}")

    def _tree_json(self) -> str:
        try:
            return json.dumps(self.sap.snapshot().to_dict())
        except Exception as e:  # noqa: BLE001
            logger.warning("snapshot failed: %s", e)
            return "{}"
