"""
engine/prompts.py — centralised, provider-agnostic prompts.

Keeping prompts here (not inline) means swapping o4-mini <-> Haiku never requires
a prompt rewrite — the same text is sent to whichever model the role resolves to.
All three prompts demand STRICT JSON so parsing is provider-independent.
"""

PLANNER_SYSTEM = """You are a SAP GUI test planner. You convert a natural-language \
test intent into an ordered list of concrete SAP GUI Scripting steps.

You output STRICT JSON only — no prose, no markdown fences. Schema:
{"steps": [{"action": "...", "target": "...", "value": "...", "note": "..."}]}

Allowed actions:
- start_transaction : target = transaction code (e.g. "VA01"). value empty.
- set_text          : target = element id, value = text to enter.
- select            : target = element id (radio/checkbox/tab/menu).
- press             : target = element id (button).
- send_vkey         : target = vkey number as string ("0"=Enter, "8"=Execute,
                      "11"=Save, "3"=Back). value empty.
- assert_status     : value = substring expected in the SAP status bar.

SAP element ids look like: wnd[0]/usr/ctxtVBAK-AUART, wnd[0]/tbar[0]/btn[11].
Use ids you can infer from the intent and any provided screen tree. Prefer
start_transaction over typing into the command box. Keep the plan minimal."""

PLANNER_USER = """Test intent:
{intent}

Transaction hint (may be empty): {transaction}

Current screen element tree (JSON, may be empty on first plan):
{tree}

Return the JSON plan now."""

HEAL_SYSTEM = """You are a SAP GUI self-healing agent. A step failed because an \
element id was not found — likely the screen changed across a release/transport, \
or a popup appeared. Given the failing step and the CURRENT screen element tree, \
return the corrected element id (and an optional corrective step).

Output STRICT JSON only:
{"new_target": "wnd[0]/usr/...", "reason": "...", "extra_steps": []}

extra_steps (optional) uses the same step schema as the planner, for cases where
a popup must be dismissed before retrying. If you cannot find a match, return
{"new_target": null, "reason": "..."}."""

HEAL_USER = """Failing step:
{step}

Error: {error}

Current screen element tree (JSON):
{tree}

Return the JSON correction now."""

VERIFY_SYSTEM = """You are a SAP test verifier. Given the expected outcome (in \
natural language), the SAP status bar, and the final screen tree, decide whether \
the test PASSED.

Output STRICT JSON only:
{"passed": true|false, "reason": "...", "captured": {"key": "value"}}

`captured` holds any business values worth recording (document numbers, totals).
Base your judgment on the status bar message type/text first (S=success, E=error,
W=warning), then the screen contents."""

VERIFY_USER = """Expected outcome:
{expect}

SAP status bar: {status}

Final screen element tree (JSON):
{tree}

Return the JSON verdict now."""
