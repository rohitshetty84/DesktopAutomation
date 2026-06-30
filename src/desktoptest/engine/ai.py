"""
engine/ai.py — the AI-driven steps: planner, self-healer, verifier.

Each function takes the LLMService and calls it by ROLE (planner / self_heal /
verifier), so the actual model (o4-mini now, Haiku later) is decided by config.
All three parse STRICT JSON via util.parse_json.
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional, Tuple

from ..model import LLMService
from . import prompts
from .schema import Step
from .util import parse_json

logger = logging.getLogger("desktoptest.engine.ai")


def plan(llm: LLMService, intent: str, transaction: str, tree_json: str) -> List[Step]:
    """Reasoning model: NL intent -> ordered Steps."""
    out = llm.ask(
        "planner",
        prompts.PLANNER_SYSTEM,
        prompts.PLANNER_USER.format(intent=intent, transaction=transaction or "",
                                    tree=tree_json or "{}"),
    )
    data = parse_json(out)
    steps = [Step(action=s.get("action", ""), target=str(s.get("target", "")),
                  value=str(s.get("value", "")), note=s.get("note", ""))
             for s in data.get("steps", [])]
    for s in steps:
        s.validate()
    logger.info("planner produced %d steps", len(steps))
    return steps


def heal(llm: LLMService, step: Step, error: str, tree_json: str,
         image_b64: Optional[str] = None) -> Tuple[Optional[str], List[Step], str]:
    """
    Reasoning model: given a failed step + current tree, return
    (new_target, extra_steps, reason). Uses vision when a screenshot is supplied.
    """
    sys, usr = prompts.HEAL_SYSTEM, prompts.HEAL_USER.format(
        step=json.dumps(step.__dict__), error=error, tree=tree_json or "{}")
    out = (llm.vision("self_heal", sys, usr, image_b64)
           if image_b64 else llm.ask("self_heal", sys, usr))
    data = parse_json(out)
    new_target = data.get("new_target")
    extra = [Step(action=s.get("action", ""), target=str(s.get("target", "")),
                  value=str(s.get("value", "")), note=s.get("note", ""))
             for s in data.get("extra_steps", []) or []]
    for s in extra:
        s.validate()
    return new_target, extra, data.get("reason", "")


def verify(llm: LLMService, expect: str, status: dict, tree_json: str) -> Tuple[bool, str, dict]:
    """General model: decide pass/fail against the NL expectation."""
    out = llm.ask(
        "verifier",
        prompts.VERIFY_SYSTEM,
        prompts.VERIFY_USER.format(expect=expect or "(none)",
                                   status=json.dumps(status), tree=tree_json or "{}"),
    )
    data = parse_json(out)
    return bool(data.get("passed", False)), data.get("reason", ""), data.get("captured", {})
