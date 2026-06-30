"""
engine/schema.py — the data contract between YAML tests, the planner, and the
executor. A test is an intent + steps; the planner turns NL intent into a list
of concrete Steps; the executor runs them and produces StepResults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# Allowed primitive actions the executor knows how to perform on SapSession.
ACTIONS = {"start_transaction", "set_text", "press", "select", "send_vkey", "assert_status"}


@dataclass
class Step:
    action: str                       # one of ACTIONS
    target: str = ""                  # element id, tcode, or vkey (as string)
    value: str = ""                   # text to set / expected substring for assert
    note: str = ""                    # human-readable description

    def validate(self) -> None:
        if self.action not in ACTIONS:
            raise ValueError(f"Unknown action {self.action!r}; allowed: {sorted(ACTIONS)}")


@dataclass
class TestCase:
    __test__ = False  # tell pytest this dataclass is not a test class
    name: str
    intent: str                       # natural-language description of the goal
    transaction: str = ""             # optional hint, e.g. "VA01"
    expect: str = ""                  # NL assertion checked by the verifier
    steps: List[Step] = field(default_factory=list)   # cached deterministic plan


@dataclass
class StepResult:
    step: Step
    ok: bool
    detail: str = ""
    healed: bool = False
    new_target: Optional[str] = None  # set when self-heal remapped an element


@dataclass
class RunResult:
    test: TestCase
    passed: bool
    results: List[StepResult] = field(default_factory=list)
    verification: str = ""
    healing_log: List[dict] = field(default_factory=list)
