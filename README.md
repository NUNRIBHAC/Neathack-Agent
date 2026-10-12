# DisruptRadar — Competitive Intelligence Agent
<img width="1280" height="800" alt="954030ba23a77659b91faf4a9269cef93779a0ec15825999f8e8fbd5cac164c4" src="https://github.com/user-attachments/assets/0a30376c-532b-4c47-9b84-b9fb8f937c07" />

Autonomous agent for neatHack 2026: monitors headcount growth signals for a target
domain, analyzes hiring velocity, verifies the indicator math and produces an
executive report.

- Repository: https://github.com/NUNRIBHAC/Neathack-Agent
- Real neatlogs trace (07:16PM, 7 spans, risk HIGH, verification True):
 https://app.neatlogs.com/traces?pageSize=100&from=2026-10-10T23%3A00%3A00.000Z&to=2026-10-12T22%3A59%3A00.000Z&orgId=7526b7af-8d30-45b5-9dc4-741078f5b938&projectId=4668228e-656b-4e5b-83b6-b1a6ebd49c91&groupBy=none&timezone=Europe%2FLisbon
- Tests: 5 passed (`pytest test_agent.py -v`)
- Entire: https://entire.io/gh/NUNRIBHAC/Neathack-Agent

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
  `5b5173b4db9c8f9b75b0c915d33ba0f1` (7 spans, HIGH, verified true) and probe traces
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
| neatlogs | ✅ | 12 traces:<br>• `54bc29bf746dc54de39246fb610972f3` (2 spans, probe) — [link](https://app.neatlogs.com/traces/54bc29bf746dc54de39246fb610972f3?orgId=7526b7af-8d30-45b5-9dc4-741078f5b938&projectId=4668228e-656b-4e5b-83b6-b1a6ebd49c91)<br>• `1227b34965a84a879ae6a00f29a901f8` (2 spans, probe) — [link](https://app.neatlogs.com/traces/1227b34965a84a879ae6a00f29a901f8?orgId=7526b7af-8d30-45b5-9dc4-741078f5b938&projectId=4668228e-656b-4e5b-83b6-b1a6ebd49c91)<br>• `5b5173b4db9c8f9b75b0c915d33ba0f1` (7 spans, HIGH, verified true, openai.com +40.0%) — [link](https://app.neatlogs.com/traces/5b5173b4db9c8f9b75b0c915d33ba0f1?orgId=7526b7af-8d30-45b5-9dc4-741078f5b938&projectId=4668228e-656b-4e5b-83b6-b1a6ebd49c91)<br>• `6d1327dced7976b98c204f2c4344bc73` (9 spans, LOW, verified false, growth_metrics 404) — [link](https://app.neatlogs.com/traces/6d1327dced7976b98c204f2c4344bc73?orgId=7526b7af-8d30-45b5-9dc4-741078f5b938&projectId=4668228e-656b-4e5b-83b6-b1a6ebd49c91)<br>• `e5247d013a358be3cfb51d696e5e6815` (9 spans, LOW, verified false, enrich 400) — [link](https://app.neatlogs.com/traces/e5247d013a358be3cfb51d696e5e6815?orgId=7526b7af-8d30-45b5-9dc4-741078f5b938&projectId=4668228e-656b-4e5b-83b6-b1a6ebd49c91)<br>• `fb4a7e3f32c21cd7cb4530fa87c50ac9` (9 spans, LOW, verified false, sem headcounts) — [link](https://app.neatlogs.com/traces/fb4a7e3f32c21cd7cb4530fa87c50ac9?orgId=7526b7af-8d30-45b5-9dc4-741078f5b938&projectId=4668228e-656b-4e5b-83b6-b1a6ebd49c91)<br>• `97d61923a997ed4f43b0c42e3397fb9f` (6 spans, LOW, verified true, retool.com -3.5%) — [link](https://app.neatlogs.com/traces/97d61923a997ed4f43b0c42e3397fb9f?orgId=7526b7af-8d30-45b5-9dc4-741078f5b938&projectId=4668228e-656b-4e5b-83b6-b1a6ebd49c91)<br>• `40c1a73aeb13c2bfd3bf4ff144f64a4c` (6 spans, LOW, verified true, retool.com -3.5%) — [link](https://app.neatlogs.com/traces/40c1a73aeb13c2bfd3bf4ff144f64a4c?orgId=7526b7af-8d30-45b5-9dc4-741078f5b938&projectId=4668228e-656b-4e5b-83b6-b1a6ebd49c91)<br>• `0e3a83a28bfc9a85421a3132312d1549` (6 spans, HIGH, verified true, openai.com +40.0%) — [link](https://app.neatlogs.com/traces/0e3a83a28bfc9a85421a3132312d1549?orgId=7526b7af-8d30-45b5-9dc4-741078f5b938&projectId=4668228e-656b-4e5b-83b6-b1a6ebd49c91)<br>• `04376a4e5346935fc6bcfb961c6d3209` (6 spans, HIGH, verified true, openai.com +30.4%) — [link](https://app.neatlogs.com/traces/04376a4e5346935fc6bcfb961c6d3209?orgId=7526b7af-8d30-45b5-9dc4-741078f5b938&projectId=4668228e-656b-4e5b-83b6-b1a6ebd49c91)<br>• `9df59489d977cd24bebd7b8f02445e94` (6 spans, HIGH, verified true, anthropic.com +41.2%) — [link](https://app.neatlogs.com/traces/9df59489d977cd24bebd7b8f02445e94?orgId=7526b7af-8d30-45b5-9dc4-741078f5b938&projectId=4668228e-656b-4e5b-83b6-b1a6ebd49c91)<br>• `85b9cc2415cf1533a17714a5ccc901a9` (6 spans, HIGH, verified true, openai.com +30.4%, LLM report) — [link](https://app.neatlogs.com/traces/85b9cc2415cf1533a17714a5ccc901a9?orgId=7526b7af-8d30-45b5-9dc4-741078f5b938&projectId=4668228e-656b-4e5b-83b6-b1a6ebd49c91) |

> **Probes (HTTP contract):** `54bc29bf...` and `1227b349...` use `test-model` with pricing `unpriced/unknown_model`: these are the HTTP contract probes described in section 2 (2x, 06:43PM). Consistent.
>
> **Distinct retool.com executions:** `97d61923...` and `40c1a73a...` are separate runs of the same domain (retool.com, -3.48%, 416/431), not duplicates.

| Entire | ✅ | `commit_linking: always`, PR #1 (`3ac4c3c`), local atomic checkpoints |
| cfo.ai | ✅ | `docs/DisruptRadar_Modelo_Financeiro (DisruptRadar_Modelo_Financeiro-ENG) and docs/Financial model (2 pages) (Financial model (2 pages)-ENG)`|

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
<img width="1280" height="900" alt="4ae46a9d69d78aaa1248ad01e6035739350cfbddce67fddce54b063c26ddc01d" src="https://github.com/user-attachments/assets/e9e72075-3dbe-4cc2-b04d-6124ec59d9ac" />
<img width="1280" height="800" alt="c1d4a1a51bafdfac5a140f30f8f28230cf512c2f0484d1e04622eb5226cb78b2" src="https://github.com/user-attachments/assets/54bc1672-ca47-44ae-875a-afc6f0787e82" />
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

## 9. Financial model docs

**Start with the approved scenarios.** The Base case has €30,096 revenue, €15,120
costs and €14,976 EBITDA. Pessimistic remains €8,000 / €6,000 / €2,000; Optimistic
remains €80,000 / €24,000 / €56,000 and is conditional. These are annual planning
scenarios, not observed results.

**The assumptions that drive the forecast.** The approved Pro price is €99/month.
Average usage is assumed to be 10 domains per customer, at an estimated
€3/domain/month: €30 of delivery costs per customer-month. Opening cash is €20,000.
Usage and vendor costs still need validation against actual consumption and invoices.

**The Base monthly forecast controls.** The Base forecast uses €6,000 of annual fixed
costs, or €500/month. The forecast runs from January to December 2027. The customer
curve is your supplied plan; changing a saved input changes the calculations that
read it.

**Follow customers into earnings and cash.** Monthly revenue uses month-end customers
x €99, with no proration. Delivery costs follow customer volumes; fixed costs stay at
€500/month. January EBITDA is -€431, February -€224 and March +€121. Collections and
payments are assumed to occur in the same month; taxes and capital expenditure are
excluded.

**Check that the annual numbers tie.** The curve totals 304 customer-months: €30,096
revenue, €9,120 delivery costs and €6,000 fixed costs produce €14,976 EBITDA.
Revenue, cost and EBITDA differences against the Base matrix are all zero. Minimum
monthly closing cash is €19,345; year-end cash is €34,976.

**Test a higher price without changing the plan.** Try €99, €109 or €119/month. This
control changes only the simulator preview, not the saved scenarios or tables. The
approved price remains €99. A higher price helps only if lost demand does not consume
the extra contribution.

**Stress-test the pitch with demand loss.** Demand loss reduces customer volumes
proportionally in every month. Revenue and avoidable delivery costs fall; fixed costs
remain unchanged. At €109 with 10% demand loss, annual EBITDA is €15,614.40; at €119
with 20% loss, it is €15,644.80. These are sensitivity tests, not measured price
elasticity.

**How much demand can you afford to lose?** With €30 delivery costs per customer-month
and €500/month fixed costs, €109 can tolerate 12.658% demand loss and €119 can
tolerate 22.472%, while matching Base EBITDA of €14,976. These thresholds update with
the simulated price and costs. Customer-months measure annual volume, not year-end
customers.

**Break-even is a different threshold.** Under the Base cost assumptions, EBITDA zero
requires 86.96 / 75.95 / 67.42 customer-months at €99 / €109 / €119. Whole-number
minimums are 87 / 76 / 68. Twelve year-end customers do not establish the pessimistic
case's annual volume or prove that it covers costs.

**Challenge the vendor cost estimate.** Try changing the cost per domain from €3 to
€4. With 304 customer-months, 10 domains per customer and no demand loss, that reduces
annual EBITDA and closing cash by €3,040. The control changes the preview only.
Actual savings depend on how the vendor really charges.

**Fixed costs do not fall with demand.** Try €300, €400 or €500/month. With the
approved €99 price and no demand loss, annual EBITDA is €17,376 / €16,176 / €14,976
respectively. The approved Base uses €500. The nine-cell reference grid is a saved
constant-demand comparison; it does not update when you move the preview controls.

**See when the decision affects cash.** The chart compares saved Base cash with the
simulated path. Check the minimum monthly balance as well as the year-end balance:
annual profit alone can hide a funding gap. The projection assumes same-month
collections and payments and excludes taxes, investment and financing.

**Keep the Optimistic condition visible.** The €56,000 Optimistic EBITDA depends on an
effective delivery cost of €2.59875/domain/month, with €3,000 annual fixed costs: a
required 13.375% reduction versus €3. That discount is not confirmed. The calculation
uses Pro-equivalent customer-months, not an Enterprise sales mix.

<img width="425" height="92" alt="Captura de ecrã 2026-10-12 124306" src="https://github.com/user-attachments/assets/51418494-b055-4f5b-810c-0ac79d5ff389" />
<img width="220" height="67" alt="Captura de ecrã 2026-10-12 124418" src="https://github.com/user-attachments/assets/148832b2-3f39-4d37-b9a0-ca3fb803095a" />
<img width="177" height="46" alt="Captura de ecrã 2026-10-12 124325" src="https://github.com/user-attachments/assets/ab29ed98-f9c5-4c20-90c5-0c327f1009fe" />
<img width="225" height="52" alt="Captura de ecrã 2026-10-12 125333" src="https://github.com/user-attachments/assets/13190c9b-2087-49f0-9725-8cd30660a268" />



