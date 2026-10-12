# DisruptRadar — Competitive Intelligence Agent

Autonomous agent for neatHack 2026: monitors headcount growth signals for a target
domain, analyzes hiring velocity, verifies the indicator math and produces an
executive report.

- Repository: https://github.com/NUNRIBHAC/Neathack-Agent
- Real neatlogs trace (07:16PM, 8 spans, risk HIGH, verification True):
  http://app.neatlogs.com/traces/5b5173b4db9c8f9b75b0c915d33ba0f1?orgId=7526b7af-8d30-45b5-9dc4-741078f5b938&projectId=4668228e-656b-4e5b-83b6-b1a6ebd49c91&returnTo=%2Ftraces%3Ffrom%3D2026-09-27T23%253A00%253A00.000Z%26to%3D2026-10-11T22%253A59%253A59.999Z%26orgId%3D7526b7af-8d30-45b5-9dc4-741078f5b938%26projectId%3D4668228e-656b-4e5b-83b6-b1a6ebd49c91%26groupBy%3Dnone%26timezone%3DEurope%252FLisbon
- Tests: 5 passed (`pytest test_agent.py -v`)

## Live demo

Try the live website: https://intel-radar-1.preview.emergentagent.com/

You can log in three ways:

1. Pre-created test account:
   - Email: `demo1@test.vc`
   - Password: `demo123` (already has domains on the watchlist: stripe.com, retool.com)
2. Admin account:
   - Email: `admin@disruptradar.io`
   - Password: `radar1234`
3. Create your own account:
   - Click "Sign up" on the login screen and register with any email + password (minimum 6 characters). You immediately get your own workspace.
   - There is also a "Continue with Google" button for social login.

## Loop architecture

```
┌────────────────────────────────────────────────────────────────────┐
│ run_agent (AGENT span)                                             │
│  1. build_plan      -> TOOL span (LLM or fixed plan)               │
│  2. FETCH_DATA      -> TOOL span (live Crustdata or fixture)       │
│  3. ANALYZE_SIGNALS -> growth_pct                                 │
│  4. VERIFY_METRICS  -> recompute + comparison (gate)              │
│  5. ASSESS_RISK     -> LOW / MEDIUM / HIGH                        │
│  6. RENDER_REPORT   -> TOOL span (LLM or offline fallback)        │
│  retry/backoff: min(1.5 * attempt, 10.0)s, max 3 attempts         │
│  atomic checkpoint (tmp + os.replace) on every transition         │
└────────────────────────────────────────────────────────────────────┘
```

## 1. Real Crustdata API mapping

- Base configurable via `CRUSTDATA_API_URL` (default `https://api.crustdata.com`),
  endpoint `POST /company/enrich`, payload
  `{"domains": ["<domain>"], "exact_match": true, "fields": ["basic_info", "headcount"]}`.
- Authentication via `Authorization: Bearer <CRUSTDATA_API_KEY>` header, plus
  `x-api-version: 2025-11-01`.
- Defensive extraction of `current_headcount` from `headcount.total` and of the
  growth percentage from `headcount.growth_percent.six_months` (fallback: `yoy`);
  `previous_headcount` is derived by reverse math: `prev = current / (1 + growth/100)`.
- The `X-Credits-Used` response header is captured as `credits_used`.
- Sanity guard: `growth_pct <= -100.0` is rejected (headcount cannot be zero or
  negative).
- In `RUN_DEMO_FIXTURE_MODE=true` there is no network traffic: synthetic data is used.

## 2. Native neatlogs SDK instrumentation

- `neatlogs.init(api_key=..., tags=["disrupt-radar"])` at startup (real signature of
  SDK 1.1.8: `init(api_key, tags, debug)`).
- Manual spans via `LLMTracker.start_llm_span(...)` / `end_llm_span(...)` at the
  critical points: `run_agent` (AGENT), `build_plan` (TOOL), `fetch_data` (TOOL) and
  `call_bedrock` (TOOL). All spans share the session `trace_id`, forming one trace per
  execution.
- SDK 1.1.8 sends to `https://app.neatlogs.com/api/data/v2` (endpoint fixed in
  `core.py`). A probe confirmed this endpoint is deprecated (404).
- Real transport: `send_trace_v1()` makes a single `POST /v1/trace` per execution
  (never per span), with `Authorization: Bearer <NEATLOGS_API_KEY>` and a nested JSON
  object (`children`). The destination is configurable via `NEATLOGS_ENDPOINT`
  (default `https://ingest.neatlogs.com/`). Evidence: trace
  `5b5173b4db9c8f9b75b0c915d33ba0f1` (8 spans, HIGH, verified true) and probe traces
  (2x, 06:43PM).
- Without `NEATLOGS_API_KEY`, telemetry degrades to no-op (both `init` and
  `send_trace_v1` skip sending).

## 3. Atomic persistence (Entire pattern)

- `RunState.save_checkpoint()` writes `artifacts/checkpoint_<run_id>.json` via a
  `.tmp` file + `os.replace()` (atomic on the same filesystem).
- The full state (plan, ledger, errors, attempts, verification, risk, report) is
  persisted on every state transition.
- Local checkpoints complement the Entire commit linking (`commit_linking: always`)
  already active in the repository (PR #1 merged, `3ac4c3c`).
- entire-graph installed (`doctor`: no_egress=true, CLI 0.11.4); full index (1,704
  files, 49,508 symbols); `search` blocks on Windows (documented).

## 4. Evaluation criteria

| Mandatory pillar | Status | Evidence |
|---|---|---|
| neatlogs | ✅ | trace `5b5173b4db9c8f9b75b0c915d33ba0f1` (8 spans, HIGH, verified true) |
| Entire | ✅ | `commit_linking: always`, PR #1 (`3ac4c3c`), local atomic checkpoints |
| cfo.ai | ⏳ | `docs/business_plan.pdf` being generated (token cost vs subscriptions matrix) |

Official weights: PENDING (the server has not announced them yet; we do not fabricate
platform metrics).

## 5. Clean install

```powershell
git clone https://github.com/NUNRIBHAC/Neathack-Agent.git
cd Neathack-Agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # fill in with real keys; .env is never committed
```

## 6. Running by mode

### Demo (synthetic data + simulated failure)

In `.env`:

```
RUN_DEMO_FIXTURE_MODE=true
INJECT_LOCAL_FAULT_SIMULATION=true
```

Then:

```powershell
python agent.py
```

Expected result: simulated failure on attempt 1 (`Simulated Network Timeout Anomaly`),
recovery on attempt 2, `+40.0%`, risk HIGH, verification True.

Equivalent via environment variables in PowerShell (do not use bash syntax):

```powershell
$env:RUN_DEMO_FIXTURE_MODE="true"; $env:INJECT_LOCAL_FAULT_SIMULATION="true"; python agent.py
```

CLI flags force the modes without touching `.env`:

```powershell
python agent.py --fixture --fault
```

`--resume <run_id>` restores `artifacts/checkpoint_<RUN_ID>.json` and continues from
where it stopped.

### Live (Crustdata + LLM + neatlogs)

In `.env`:

```
RUN_DEMO_FIXTURE_MODE=false
INJECT_LOCAL_FAULT_SIMULATION=false
CRUSTDATA_API_KEY=<real key>
NEATLOGS_API_KEY=<real key>
NEATLOGS_ENDPOINT=https://ingest.neatlogs.com/
BEDROCK_MODEL_ID=<active modelId in us-east-1>
```

LLM resolution order: if `LITELLM_API_KEY` is set, the agent first tries the LiteLLM
proxy (OpenAI chat completions compatible API; `LITELLM_BASE_URL` and
`LITELLM_MODEL_ID` are configurable); on failure it falls back to Bedrock; if both
fail, the deterministic offline fallback is used.

Then:

```powershell
python agent.py --goal "Detect competitive disruptions in a target domain using headcount growth." --domain "openai.com"
```

### Tests

```powershell
pytest test_agent.py -v
```

The tests validate: simulated error capture, recovery on attempt 2, exact +40.0%
recompute, risk HIGH, verification True and the real `/v1/trace` payload contract
(5 tests).

## 7. Credentials and security

- No real key is versioned. `.env.example` contains placeholders; `.env` is in
  `.gitignore`.
- The agent validates the target domain format before any network call.
- If the log is shared, rotate the AWS/Crustdata/neatlogs keys before exposing it.

## 8. Dependencies

```
requests==2.34.2
python-dotenv==1.2.4
pydantic==2.14.0
boto3==1.43.111
pytest==9.1.1
neatlogs==1.1.8
```