# neatHack 2026 — Build Log · DisruptRadar

Log incremental e timestamped. Nunca apagar sessões anteriores.

---

## Sessão 2026-10-11 (WEST)

### Scope
- Implementar o agente DisruptRadar (inteligência competitiva via headcount) com os 3 pilares obrigatórios: neatlogs, Entire, cfo.ai.
- Repo: https://github.com/NUNRIBHAC/Neathack-Agent · branch main

### Feito e verificado
- `pytest test_agent.py -v` -> **5 passed** (7.47s)
- 5.º teste `test_send_trace_v1_payload` -> monkeypatch a `requests.post`; valida URL `/v1/trace`, `name == "disrupt-radar"`, 5 children, output HIGH/verified true
- Run fixture controlado (RUN_DEMO_FIXTURE_MODE=true + INJECT_LOCAL_FAULT_SIMULATION=true):
  1. `[1/3] Simulated Network Timeout Anomaly` (falha injetada)
  2. Recuperação na tentativa 2 -> dados fixture (140/100)
  3. `+40.0%` -> verificação matemática `True`
  4. Risco `HIGH` -> relatório executivo
- 7 checkpoints atómicos escritos -> `artifacts/checkpoint_1791730598.json` (tmp + os.replace)
- neatlogs: `init` OK, sessão `77d32de2-8c23-4db0-881d-cac30fd0872e`, tags `['disrupt-radar']`
- Entire: `commit_linking: always` ativo (settings.json .entire) + hooks Cursor

### Registo adicional 2026-10-11 (noite)
- **Merge do PR #1**: `3ac4c3c` (commit linking do Entire ativo no repo)
- **Commit do `send_trace_v1`**: transporte real de telemetria (POST `/v1/trace`)
- **Probe HTTP**: endpoint v2 do SDK (`/api/data/v2`) -> **404** (descontinuado);
  endpoint v1 (`https://ingest.neatlogs.com/v1/trace`) -> **200** com Bearer token
  (2 traces de probe gerados, 06:43PM)
- **Trace real do agente**: `5b5173b4db9c8f9b75b0c915d33ba0f1` (07:16PM, 8 spans,
  risco HIGH, verificação True) — evidência end-to-end no dashboard:
  http://app.neatlogs.com/traces/5b5173b4db9c8f9b75b0c915d33ba0f1?orgId=7526b7af-8d30-45b5-9dc4-741078f5b938&projectId=4668228e-656b-4e5b-83b6-b1a6ebd49c91&returnTo=%2Ftraces%3Ffrom%3D2026-09-27T23%253A00%253A00.000Z%26to%3D2026-10-11T22%253A59%253A59.999Z%26orgId%3D7526b7af-8d30-45b5-9dc4-741078f5b938%26projectId%3D4668228e-656b-4e5b-83b6-b1a6ebd49c91%26groupBy%3Dnone%26timezone%3DEurope%252FLisbon
- **Decisão de fluxo**: a partir de agora, todo o trabalho é feito na branch do
  Entire (nunca diretamente na `main`), para o hook capturar todas as sessões.
- **entire-graph**: `entire graph index --repo . --force` -> 2m24s, 1.704 ficheiros,
  49.508 símbolos, "completeness: ok"; `doctor` -> no_egress=true, CLI 0.11.4;
  `search` bloqueia no Windows (2 tentativas), pendente de fix do CLI

### Diagnóstico Bedrock (probe, depois removido do repo)
- `anthropic.claude-3-5-sonnet-20240620-v1:0` -> ResourceNotFoundException (fim de vida)
- 3.x (3.7, 3.5 v2, haiku 3.x, opus 3) -> fim de vida
- 4.5 Sonnet/Haiku, com e sem prefixo `us.` -> "The provided model identifier is invalid"
- IAM `hackathon-user-010`: só permite `bedrock:InvokeModel`; listagem e inference profiles -> AccessDenied
- Conclusão: modelId ativo desconhecido; aguarda mentores. Bedrock é serviço opcional; demo corre em fixture.

### Pendente
- cfo.ai -> `docs/business_plan.pdf` (matriz custo de tokens vs subscrições)
- README de apresentação com links reais de traces (atualizado; falta colar no IDE + commit/push)
- `probe_models.py` não entra no repo (removido)
- Demo video 2–3 min + posts X `#neatHack` (ação do utilizador)
- Submissão: quote-tweet segunda 19:00–23:55 IST (19:25–00:00 hora de Lisboa)

probe_neatlogs.py
import os

import requests
from dotenv import load_dotenv

load_dotenv()

key = os.getenv("NEATLOGS_API_KEY", "").strip()
if not key:
    print("NEATLOGS_API_KEY em falta no .env")
    raise SystemExit(1)

trace = {
    "name": "disrupt-radar",
    "kind": "WORKFLOW",
    "input": {"goal": "probe de contratos HTTP"},
    "children": [
        {
            "name": "probe_llm",
            "kind": "LLM",
            "model": "test-model",
            "input": "ping",
            "output": "pong",
            "tokens": {"prompt": 1, "completion": 1, "total": 2},
        }
    ],
}

targets = [
    ("Bearer token (doc oficial)",
     {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}),
    ("x-api-key (SDK style)",
     {"x-api-key": key, "Content-Type": "application/json"}),
]

for label, headers in targets:
    try:
        r = requests.post(
            "https://ingest.neatlogs.com/v1/trace",
            json=trace,
            headers=headers,
            timeout=15,
        )
        print(label, "->", r.status_code, r.text[:300])
        if r.status_code == 200:
            body = r.json()
            print("  trace_id:", body.get("trace_id"), "| spans:", body.get("spans"))
    except Exception as exc:
        print(label, "-> ERRO", exc)