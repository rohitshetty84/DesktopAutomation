"""
Offline unit tests — no Azure, no SAP, no network.

They drive the AdaptiveEngine with a FakeLLM and a dry-run SapSession to prove
the orchestration (plan -> execute -> verify, and the self-heal path) works.
Run:  pytest -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from desktoptest.engine import AdaptiveEngine, TestCase, Step  # noqa: E402
from desktoptest.sap import SapSession  # noqa: E402


class FakeLLM:
    """Stand-in for LLMService: deterministic JSON-free responses by role."""
    def __init__(self, heal_target="wnd[0]/usr/NEW", passed=True):
        self.heal_target = heal_target
        self.passed = passed
        self.calls = []

    def ask(self, role, system, user, **kw):
        self.calls.append(role)
        if role == "planner":
            return '{"steps":[{"action":"start_transaction","target":"VA01"}]}'
        if role == "self_heal":
            return f'{{"new_target":"{self.heal_target}","reason":"remapped","extra_steps":[]}}'
        if role == "verifier":
            return f'{{"passed":{str(self.passed).lower()},"reason":"ok","captured":{{}}}}'
        return "{}"

    def vision(self, role, system, user, image_b64, **kw):
        return self.ask(role, system, user)


def test_happy_path_explicit_steps():
    sap = SapSession(session=None, dry_run=True)
    engine = AdaptiveEngine(FakeLLM(), sap)
    test = TestCase(name="t", intent="do thing", expect="works",
                    steps=[Step(action="start_transaction", target="VA01"),
                           Step(action="set_text", target="wnd[0]/usr/x", value="1")])
    result = engine.run(test)
    assert result.passed
    assert all(r.ok for r in result.results)


def test_planner_used_when_no_steps():
    sap = SapSession(session=None, dry_run=True)
    llm = FakeLLM()
    engine = AdaptiveEngine(llm, sap)
    test = TestCase(name="t", intent="open VA01", expect="works")
    result = engine.run(test)
    assert "planner" in llm.calls
    assert result.passed


def test_self_heal_remaps_and_retries(monkeypatch):
    # Force the first set_text to fail once, then succeed after heal rewrites target.
    sap = SapSession(session=None, dry_run=True)
    original = sap.set_text
    state = {"failed": False}

    def flaky_set_text(element_id, value):
        if element_id == "wnd[0]/usr/OLD" and not state["failed"]:
            state["failed"] = True
            raise RuntimeError("Element not found: wnd[0]/usr/OLD")
        return original(element_id, value)

    monkeypatch.setattr(sap, "set_text", flaky_set_text)
    engine = AdaptiveEngine(FakeLLM(heal_target="wnd[0]/usr/NEW"), sap,
                            use_vision_heal=False)
    test = TestCase(name="t", intent="x", expect="works",
                    steps=[Step(action="set_text", target="wnd[0]/usr/OLD", value="1")])
    result = engine.run(test)
    assert result.passed
    assert result.results[0].healed
    assert result.results[0].new_target == "wnd[0]/usr/NEW"
    assert len(result.healing_log) == 1


def test_verifier_failure_marks_run_failed():
    sap = SapSession(session=None, dry_run=True)
    engine = AdaptiveEngine(FakeLLM(passed=False), sap)
    test = TestCase(name="t", intent="x", expect="works",
                    steps=[Step(action="send_vkey", target="0")])
    result = engine.run(test)
    assert result.passed is False
