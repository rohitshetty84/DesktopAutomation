# AI_DesktopTest Automation

AI-guided **desktop** test automation — an RPA-style bot for **SAP GUI for Windows**,
driven by **Azure-hosted** models (o4-mini now, Haiku stub ready).

It applies the **Adaptive architecture**: a deterministic happy path with **no AI
in the loop**, plus AI for one-time planning, **self-healing** when SAP screens
change, and natural-language **verification** of outcomes.

```
YAML test ─► Planner (once) ─► Execute deterministically ─► Verify ─► HTML report
                                      │
                                    step fails
                                      ▼
                               Self-heal (AI) ─► retry ─► rewrite cached step
```

## Why SAP GUI is a good fit

SAP GUI ships a built-in **Scripting API**: every field/button has a stable id
(`wnd[0]/usr/ctxtVBAK-AUART`), so the bot reads/sets values directly — no
coordinates, no vision guessing. The AI sits *on top* (authoring, healing,
verifying), not driving pixels.

## Layout

```
config/models.yaml          role -> model routing (planner/verifier/self_heal/fallback)
src/desktoptest/
  model/                    provider-agnostic LLMService
    azure_openai_adapter.py   WORKING: o4-mini / gpt-4o via openai SDK
    azure_foundry_adapter.py  STUB: Haiku via Azure AI Foundry (fill in to enable)
    service.py                config-driven, role-based router + retry/fallback
  sap/session.py            SAP GUI Scripting wrapper (pywin32 COM); dry-run off-Windows
  engine/                   Adaptive orchestrator: plan / execute / self-heal / verify
tests/                      YAML test cases (e.g. va01_create_order.yaml)
tests_py/                   offline pytest suite (no Azure / no SAP)
run.py                      CLI runner -> HTML reports in reports/
docs/                       design document
```

## Setup

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                              # then fill in Azure + SAP values
```

**SAP prerequisites (Windows):** enable scripting server-side
(`sapgui/user_scripting = TRUE`) and client-side (SAP GUI Options → Accessibility
& Scripting → Scripting), and disable the attach/connect warning popups for
unattended runs.

Each test run launches its own **fresh SAP GUI session** via `sapshcut.exe`
(`SAP_CONNECTION` + `SAP_CLIENT` in `.env`) and closes it again when the run
finishes — SSO handles login, so no `SAP_USER`/`SAP_PASSWORD` is needed. You
don't need SAP Logon already open; just SSO configured for unattended login.

## Run

```bash
python run.py tests/va01_create_order.yaml        # one test
python run.py tests/                               # a folder
python run.py tests/ --no-vision-heal              # text-only self-heal
pytest                                             # offline unit tests
```

Off-Windows or with `SAP_DRY_RUN=true`, the SAP layer mocks actions so you can
smoke-test the wiring anywhere.

## Dashboard

A local web dashboard (`studio/`) lets you browse YAML tests, trigger a run from
the browser, and watch steps execute/self-heal live, alongside a run history view
— modeled on the sibling Playwright AI Studio's look (FastAPI + a single static
HTML/JS page, no build step).

```bash
./run_server.sh                 # http://localhost:8501 (PORT in .env to override)
```

Run history is written to `reports/runs/*.json` (one file per run, whether
triggered via the dashboard or `python run.py`) alongside the existing static
HTML reports. Dashboard-triggered runs are serialized one at a time — SAP GUI
Scripting isn't safe to drive from multiple threads against one attached session.

## The model layer (o4-mini + Haiku)

Ported and generalised from the Playwright studio's two-client router: it now
branches on **provider**, not just deployment, behind one `LLMService` interface
(`ask` / `vision`). Roles map to models in `config/models.yaml`:

```yaml
roles:   {planner: reasoning, verifier: general, self_heal: reasoning, fallback: general}
```

- **o4-mini / gpt-4o** → `AzureOpenAIAdapter` (working). Handles the reasoning-model
  quirks: no `temperature`, `max_completion_tokens` instead of `max_tokens`.
- **Haiku** → `AzureFoundryAdapter` (**stub**). Haiku on Azure is served via Azure
  AI Foundry, which the `openai` SDK cannot call. To enable: implement the two
  methods (Azure AI Inference SDK *or* LiteLLM — both sketched in the file), set
  the `AZURE_FOUNDRY_*` env vars, and point a role at `haiku`. No other code changes.

See `docs/Design_AI_Desktop_Test_Automation.md` for the full design.
