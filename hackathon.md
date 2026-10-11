# neatHack 2026 — Build Log · DisruptRadar

Log incremental e timestamped. Nunca apagar sessões anteriores.

---

## Sessão 2026-10-11 (WEST)

### Scope
- Implementar o agente DisruptRadar (inteligência competitiva via headcount) com os 3 pilares obrigatórios: neatlogs, Entire, cfo.ai.
- Repo: https://github.com/NUNRIBHAC/Neathack-Agent · branch main

### Feito e verificado
- `pytest test_agent.py -v` -> **4 passed** (0.99s)
- Run fixture controlado (RUN_DEMO_FIXTURE_MODE=true + INJECT_LOCAL_FAULT_SIMULATION=true):
  1. `[1/3] Simulated Network Timeout Anomaly` (falha injetada)
  2. Recuperação na tentativa 2 -> dados fixture (140/100)
  3. `+40.0%` -> verificação matemática `True`
  4. Risco `HIGH` -> relatório executivo
- 7 checkpoints atómicos escritos -> `artifacts/checkpoint_1791730598.json` (tmp + os.replace)
- neatlogs: `init` OK, sessão `77d32de2-8c23-4db0-881d-cac30fd0872e`, tags `['disrupt-radar']`
- Entire: `commit_linking: always` ativo (settings.json .entire) + hooks Cursor

### Diagnóstico Bedrock (probe, depois removido do repo)
- `anthropic.claude-3-5-sonnet-20240620-v1:0` -> ResourceNotFoundException (fim de vida)
- 3.x (3.7, 3.5 v2, haiku 3.x, opus 3) -> fim de vida
- 4.5 Sonnet/Haiku, com e sem prefixo `us.` -> "The provided model identifier is invalid"
- IAM `hackathon-user-010`: só permite `bedrock:InvokeModel`; listagem e inference profiles -> AccessDenied
- Conclusão: modelId ativo desconhecido; aguarda mentores. Bedrock é serviço opcional; demo corre em fixture.

### Pendente
- cfo.ai -> `docs/business_plan.pdf` (matriz custo de tokens vs subscrições)
- README de apresentação com links reais de traces
- `probe_models.py` não entra no repo (removido)
- Demo video 2–3 min + posts X `#neatHack` (ação do utilizador)
- Submissão: quote-tweet segunda 19:00–23:55 IST (19:25–00:00 hora de Lisboa)