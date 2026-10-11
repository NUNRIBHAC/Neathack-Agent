# DisruptRadar — Notas de Implementação (para os juízes)

## 1. Mapeamento real da API Crustdata
- Base configurável por `CRUSTDATA_API_URL` (default `https://api.crustdata.com`),
  endpoint `POST /company/growth_metrics`, payload `{"company_domain": "<domínio>"}`.
- Autenticação por header `Authorization: Token <CRUSTDATA_API_KEY>`.
- Extração defensiva de `current_headcount`/`previous_headcount` de dicionários
  imbricados; se a API devolver apenas a percentagem de crescimento, o valor em
  falta é derivado por matemática inversa.
- Em `RUN_DEMO_FIXTURE_MODE=true` não há tráfego de rede: usa dados sintéticos.

## 2. Instrumentação nativa do SDK neatlogs
- `neatlogs.init(api_key=..., tags=["disrupt-radar"])` no arranque (assinatura real
  do SDK 1.1.8: `init(api_key, tags, debug)`).
- Spans manuais via `LLMTracker.start_llm_span(...)` / `end_llm_span(...)` nos
  pontos críticos: `run_agent` (AGENT), `build_plan` (TOOL), `fetch_data` (TOOL)
  e `call_bedrock` (TOOL). Todos os spans partilham o `trace_id` da sessão,
  formando um trace por execução.
- O SDK 1.1.8 envia para `https://app.neatlogs.com/api/data/v2` (endpoint fixo
  no `core.py`); `NEATLOGS_ENDPOINT` fica documentado mas não é consumido por
  esta versão. Sem `NEATLOGS_API_KEY`, a telemetria degrada para no-op.

## 3. Persistência atómica (padrão Entire)
- `RunState.save_checkpoint()` grava `artifacts/checkpoint_<run_id>.json` via
  ficheiro `.tmp` + `os.replace()` (atómico no mesmo filesystem).
- O estado completo (plan, ledger, erros, tentativas, verificação, risco,
  relatório) é persistido entre execuções.
- Os checkpoints locais complementam o commit linking do Entire
  (`commit_linking: always`) já ativo no repositório.

## Notas de execução
- Reproduzir o cenário de falha -> auto-recuperação -> verificação:
RUN_DEMO_FIXTURE_MODE=true INJECT_LOCAL_FAULT_SIMULATION=true python agent.py
- Os testes validam: captura do erro simulado, recuperação na tentativa 2,
recálculo de +40.0%, risco HIGH e verificação True (pytest test_agent.py).

## Credenciais
- Nenhuma chave real é versionada. `.env.example` contém placeholders; `.env`
está no `.gitignore`.