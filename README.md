# DisruptRadar — Agente de Inteligência Competitiva

Agente autónomo para o neatHack 2026: monitoriza sinais de crescimento de headcount de um
domínio alvo, analisa a velocidade de contratação, verifica a matemática dos indicadores e
produz um relatório executivo.

- Repositório: https://github.com/NUNRIBHAC/Neathack-Agent
- Trace neatlogs real (07:16PM, 8 spans, risco HIGH, verificação True):
  http://app.neatlogs.com/traces/5b5173b4db9c8f9b75b0c915d33ba0f1?orgId=7526b7af-8d30-45b5-9dc4-741078f5b938&projectId=4668228e-656b-4e5b-83b6-b1a6ebd49c91&returnTo=%2Ftraces%3Ffrom%3D2026-09-27T23%253A00%253A00.000Z%26to%3D2026-10-11T22%253A59%253A59.999Z%26orgId%3D7526b7af-8d30-45b5-9dc4-741078f5b938%26projectId%3D4668228e-656b-4e5b-83b6-b1a6ebd49c91%26groupBy%3Dnone%26timezone%3DEurope%252FLisbon
- Testes: 5 passed (`pytest test_agent.py -v`)

## Arquitetura do loop

```
┌────────────────────────────────────────────────────────────────────┐
│ run_agent (span AGENT)                                             │
│  1. build_plan      -> span TOOL (Bedrock ou plano fixo)           │
│  2. FETCH_DATA      -> span TOOL (Crustdata live ou fixture)       │
│  3. ANALYZE_SIGNALS -> growth_pct                                 │
│  4. VERIFY_METRICS  -> recálculo + comparação (gate)              │
│  5. ASSESS_RISK     -> LOW / MEDIUM / HIGH                        │
│  6. RENDER_REPORT   -> span TOOL (Bedrock ou fallback offline)    │
│  retry/backoff: min(1.5 * tentativa, 10.0)s, máx. 3 tentativas    │
│  checkpoint atómico (tmp + os.replace) a cada transição           │
└────────────────────────────────────────────────────────────────────┘
```

## 1. Mapeamento real da API Crustdata

- Base configurável por `CRUSTDATA_API_URL` (default `https://api.crustdata.com`),
  endpoint `POST /company/growth_metrics`, payload `{"company_domain": "<domínio>"}`.
- Autenticação por header `Authorization: Token <CRUSTDATA_API_KEY>`.
- Extração defensiva de `current_headcount`/`previous_headcount` de dicionários
  imbricados; se a API devolver apenas a percentagem de crescimento, o valor em falta
  é derivado por matemática inversa.
- Guarda de sanidade: `growth_pct <= -100.0` é rejeitado (headcount não pode ser
  zero/negativo).
- Em `RUN_DEMO_FIXTURE_MODE=true` não há tráfego de rede: usa dados sintéticos.

## 2. Instrumentação nativa do SDK neatlogs

- `neatlogs.init(api_key=..., tags=["disrupt-radar"])` no arranque (assinatura real do
  SDK 1.1.8: `init(api_key, tags, debug)`).
- Spans manuais via `LLMTracker.start_llm_span(...)` / `end_llm_span(...)` nos pontos
  críticos: `run_agent` (AGENT), `build_plan` (TOOL), `fetch_data` (TOOL) e
  `call_bedrock` (TOOL). Todos os spans partilham o `trace_id` da sessão, formando um
  trace por execução.
- O SDK 1.1.8 envia para `https://app.neatlogs.com/api/data/v2` (endpoint fixo no
  `core.py`). Probe confirmou que este endpoint está descontinuado (404).
- Transporte real: `send_trace_v1()` faz um único `POST /v1/trace` por execução (nunca
  por span), com `Authorization: Bearer <NEATLOGS_API_KEY>` e um objeto JSON aninhado
  (`children`). O destino é configurável por `NEATLOGS_ENDPOINT` (default
  `https://ingest.neatlogs.com/`). Evidência: trace `5b5173b4db9c8f9b75b0c915d33ba0f1`
  (8 spans, HIGH, verified true) e traces de probe (2×, 06:43PM).
- Sem `NEATLOGS_API_KEY`, a telemetria degrada para no-op (tanto o init como o
  `send_trace_v1` saltam o envio).

## 3. Persistência atómica (padrão Entire)

- `RunState.save_checkpoint()` grava `artifacts/checkpoint_<run_id>.json` via ficheiro
  `.tmp` + `os.replace()` (atómico no mesmo filesystem).
- O estado completo (plan, ledger, erros, tentativas, verificação, risco, relatório) é
  persistido a cada transição de estado.
- Os checkpoints locais complementam o commit linking do Entire
  (`commit_linking: always`) já ativo no repositório (PR #1 merged, `3ac4c3c`).
- entire-graph instalado (`doctor`: no_egress=true, CLI 0.11.4); index completo
  (1.704 ficheiros, 49.508 símbolos); `search` bloqueia no Windows (documentado).

## 4. Critérios de avaliação

| Pilar obrigatório | Estado | Evidência |
|---|---|---|
| neatlogs | ✅ | trace `5b5173b4db9c8f9b75b0c915d33ba0f1` (8 spans, HIGH, verified true) |
| Entire | ✅ | `commit_linking: always`, PR #1 (`3ac4c3c`), checkpoints atómicos locais |
| cfo.ai | ⏳ | `docs/business_plan.pdf` em geração (matriz custo de tokens vs subscrições) |

Pesos oficiais: PENDING (o servidor ainda não os anunciou; não fabricamos métricas da
plataforma).

## 5. Instalação limpa

```powershell
git clone https://github.com/NUNRIBHAC/Neathack-Agent.git
cd Neathack-Agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # preencher com chaves reais; .env nunca é commitado
```

## 6. Execução por modo

### Demo (dados sintéticos + falha simulada)

No `.env`:

```
RUN_DEMO_FIXTURE_MODE=true
INJECT_LOCAL_FAULT_SIMULATION=true
```

Depois:

```powershell
python agent.py
```

Resultado esperado: falha simulada na tentativa 1 (`Simulated Network Timeout Anomaly`),
recuperação na tentativa 2, `+40.0%`, risco HIGH, verificação True.

Equivalente por variável de ambiente no PowerShell (não usar sintaxe bash):

```powershell
$env:RUN_DEMO_FIXTURE_MODE="true"; $env:INJECT_LOCAL_FAULT_SIMULATION="true"; python agent.py
```

### Live (Crustdata + Bedrock + neatlogs)

No `.env`:

```
RUN_DEMO_FIXTURE_MODE=false
INJECT_LOCAL_FAULT_SIMULATION=false
CRUSTDATA_API_KEY=<chave real>
NEATLOGS_API_KEY=<chave real>
NEATLOGS_ENDPOINT=https://ingest.neatlogs.com/
BEDROCK_MODEL_ID=<modelId ativo em us-east-1>
```

Depois:

```powershell
python agent.py "Detetar disrupções competitivas num domínio alvo usando crescimento de headcount." "openai.com"
```

### Testes

```powershell
pytest test_agent.py -v
```

Os testes validam: captura do erro simulado, recuperação na tentativa 2, recálculo de
+40.0%, risco HIGH e verificação True.

## 7. Credenciais e segurança

- Nenhuma chave real é versionada. `.env.example` contém placeholders; `.env` está no
  `.gitignore`.
- O agente valida o formato do domínio alvo antes de qualquer chamada de rede.
- Se o log for partilhado, rodar as chaves AWS/Crustdata/neatlogs antes de expor.

## 8. Dependências

```
requests==2.34.2
python-dotenv==1.2.4
pydantic==2.14.0
boto3==1.43.111
pytest==9.1.1
neatlogs==1.1.8
```