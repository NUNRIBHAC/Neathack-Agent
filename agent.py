"""
DisruptRadar: Autonomous Competitor Intelligence Agent
======================================================
Built for neatHack 2026.

Monitoriza sinais de crescimento de headcount de um domínio alvo, analisa a
velocidade de contratação, verifica a matemática dos indicadores e produz um
relatório executivo.

Modos de execução:
- RUN_DEMO_FIXTURE_MODE=true          -> dados sintéticos, sem rede
- INJECT_LOCAL_FAULT_SIMULATION=true  -> injeta uma falha na 1.ª tentativa
- CLI: --fixture / --fault forçam os modos acima sem tocar no .env
- CLI: --resume <run_id> restaura o checkpoint e continua de onde parou
"""

import functools
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

import boto3
import requests
from dotenv import load_dotenv

import neatlogs

load_dotenv()

# ---------------------------------------------------------------------------
# Configuração e Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("disrupt-radar")

try:
    if os.getenv("NEATLOGS_API_KEY"):
        neatlogs.init(api_key=os.getenv("NEATLOGS_API_KEY"), tags=["disrupt-radar"])
        logger.info("neatlogs iniciado (tags=['disrupt-radar'])")
    else:
        logger.warning("NEATLOGS_API_KEY em falta; telemetria desativada.")
except Exception as exc:
    logger.warning("neatlogs.init indisponível (%s); telemetria via logging.", exc)


def span(kind: str, name: str):
    """Decorator de telemetria nativa via LLMTracker (start/end_llm_span).

    Sem tracker inicializado (ou em testes), a função corre sem telemetria.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            tracker = getattr(neatlogs, "get_tracker", lambda: None)()
            if tracker is None:
                return fn(*args, **kwargs)
            op_span = tracker.start_llm_span(
                model="disrupt-radar-agent",
                provider="disruptradar",
                node_type=kind,
                node_name=name,
            )
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                tracker.end_llm_span(op_span, success=False, error=exc)
                raise
            tracker.end_llm_span(op_span, success=True)
            return result
        return wrapper
    return decorator


VALID_STEP_KEYS = {
    "FETCH_DATA",
    "ANALYZE_SIGNALS",
    "VERIFY_METRICS",
    "ASSESS_RISK",
    "RENDER_REPORT",
}

DEFAULT_PLAN = [
    "FETCH_DATA",
    "ANALYZE_SIGNALS",
    "VERIFY_METRICS",
    "ASSESS_RISK",
    "RENDER_REPORT",
]


def _parse_retry_after(value: Any) -> Optional[int]:
    """Converte Retry-After (segundos ou data HTTP) em segundos, ou None."""
    if not value:
        return None
    try:
        return max(0, int(float(str(value).strip())))
    except ValueError:
        pass
    try:
        delta = parsedate_to_datetime(str(value).strip()) - datetime.now(timezone.utc)
        return max(0, int(delta.total_seconds()))
    except Exception:
        return None


class RunState:
    """Estado persistente do agente, com checkpoint atómico."""

    def __init__(self, goal: str) -> None:
        self.run_id: int = int(time.time())
        self.goal: str = goal
        self.target_domain: str = ""
        self.plan: List[str] = []
        self.current_step_idx: int = 0
        self.evidence_ledger: List[Dict[str, Any]] = []
        self.findings: Dict[str, Any] = {}
        self.errors_log: List[Dict[str, Any]] = []
        self.task_attempts: Dict[str, int] = {}
        self.is_verified: bool = False
        self.risk_level: str = "UNKNOWN"
        self.final_report: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "goal": self.goal,
            "target_domain": self.target_domain,
            "plan": self.plan,
            "current_step_idx": self.current_step_idx,
            "evidence_ledger": self.evidence_ledger,
            "findings": self.findings,
            "errors_log": self.errors_log,
            "task_attempts": self.task_attempts,
            "is_verified": self.is_verified,
            "risk_level": self.risk_level,
            "final_report": self.final_report,
        }

    def save_checkpoint(self) -> str:
        """Persiste o estado de forma atómica: .tmp + os.replace()."""
        artifacts_dir = os.path.join(os.getcwd(), "artifacts")
        os.makedirs(artifacts_dir, exist_ok=True)
        final_path = os.path.join(artifacts_dir, f"checkpoint_{self.run_id}.json")
        tmp_path = f"{final_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, final_path)
        logger.info("Checkpoint atómico escrito em %s", final_path)
        return final_path

    @classmethod
    def load_checkpoint(cls, run_id: int) -> "RunState":
        """Restaura um estado persistido por save_checkpoint()."""
        final_path = os.path.join(
            os.getcwd(), "artifacts", f"checkpoint_{run_id}.json"
        )
        with open(final_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        state = cls(goal=data.get("goal", ""))
        state.run_id = int(data.get("run_id", run_id))
        state.target_domain = data.get("target_domain", "")
        state.plan = data.get("plan", [])
        state.current_step_idx = int(data.get("current_step_idx", 0))
        state.evidence_ledger = data.get("evidence_ledger", [])
        state.findings = data.get("findings", {})
        state.errors_log = data.get("errors_log", [])
        state.task_attempts = data.get("task_attempts", {})
        state.is_verified = bool(data.get("is_verified", False))
        state.risk_level = data.get("risk_level", "UNKNOWN")
        state.final_report = data.get("final_report", "")
        return state


class DisruptRadarAgent:
    """Agente autónomo de inteligência competitiva com recuperação de falhas."""

    @staticmethod
    def _validate_domain(domain: str) -> str:
        """Valida o formato básico de um domínio (ex.: acme.example.com)."""
        if not isinstance(domain, str):
            raise ValueError(f"target_domain inválido: {domain!r}")
        candidate = domain.strip().lower()
        if len(candidate) > 253:
            raise ValueError(f"target_domain demasiado longo: {domain!r}")
        hostname_re = re.compile(
            r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$"
        )
        if not hostname_re.match(candidate):
            raise ValueError(f"target_domain com formato inválido: {domain!r}")
        return candidate

    def __init__(
        self,
        goal: str,
        target_domain: str,
        max_retries: int = 3,
        fixture_mode: Optional[bool] = None,
        inject_fault: Optional[bool] = None,
        state: Optional[RunState] = None,
    ) -> None:
        self.goal = goal
        self.target_domain = self._validate_domain(target_domain)
        self.max_retries = max_retries

        if fixture_mode is not None:
            self.fixture_mode = fixture_mode
        else:
            self.fixture_mode = (
                os.getenv("RUN_DEMO_FIXTURE_MODE", "false").strip().lower() == "true"
            )
        if inject_fault is not None:
            self.inject_fault = inject_fault
        else:
            self.inject_fault = (
                os.getenv("INJECT_LOCAL_FAULT_SIMULATION", "false").strip().lower()
                == "true"
            )

        self.state = state if state is not None else RunState(goal)
        if state is None:
            self.state.plan = DEFAULT_PLAN[:]
        self.state.target_domain = self.target_domain

        self.bedrock = boto3.client(
            service_name="bedrock-runtime",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )

    # ------------------------------------------------------------------
    # Inferência via Amazon Bedrock
    # ------------------------------------------------------------------
    @span(kind="TOOL", name="call_bedrock")
    def call_bedrock(self, prompt: str, max_tokens: int = 1024) -> str:
        """Encapsula invocações ao modelo Claude 3.5 Sonnet via Bedrock."""
        model_id = os.getenv(
            "BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20240620-v1:0"
        )
        body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
        )
        response = self.bedrock.invoke_model(modelId=model_id, body=body)
        payload = json.loads(response["body"].read())
        content = payload.get("content", [])
        if isinstance(content, list):
            return "".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict)
            ).strip()
        if isinstance(content, dict):
            return content.get("text", "").strip()
        return str(content).strip()

    # ------------------------------------------------------------------
    # Normalização de passos
    # ------------------------------------------------------------------
    def _normalize_step(self, step: Any) -> str:
        """Normaliza strings de passos geradas por LLM para chaves padrão."""
        if not isinstance(step, str):
            step = str(step)
        step_upper = step.strip().upper().replace(" ", "_").replace("-", "_")
        for key in VALID_STEP_KEYS:
            if key in step_upper:
                return key
        return "FETCH_DATA"

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------
    @span(kind="TOOL", name="build_plan")
    def build_plan(self) -> List[str]:
        """Delega no LLM o plano; cai para plano fixo em caso de falha."""
        plan_prompt = (
            "És um planner especializado em inteligência competitiva.\n"
            "Objetivo do utilizador: {goal}\n"
            "Empresa/domínio alvo: {target_domain}\n"
            "A tua única tarefa é devolver um plano de execução em formato JSON válido.\n"
            "Regras obrigatórias:\n"
            "- Devolve APENAS um array JSON (sem markdown, sem explicações, sem backticks)\n"
            "- Máximo de 5 passos\n"
            "- Usa preferencialmente estes nomes de passos: FETCH_DATA, ANALYZE_SIGNALS, VERIFY_METRICS, ASSESS_RISK, RENDER_REPORT\n"
            "- Os passos devem ser curtos e técnicos\n"
            'Exemplo de formato correto: ["FETCH_DATA", "ANALYZE_SIGNALS", "VERIFY_METRICS", "ASSESS_RISK", "RENDER_REPORT"]'
        ).format(goal=self.goal, target_domain=self.target_domain)

        try:
            raw = self.call_bedrock(plan_prompt, max_tokens=512)
            start = raw.find("[")
            end = raw.rfind("]")
            if start != -1 and end != -1 and end > start:
                raw = raw[start : end + 1]
            parsed = json.loads(raw)
            if not isinstance(parsed, list) or not parsed:
                raise ValueError("plano não é uma lista não vazia")
            self.state.plan = [self._normalize_step(step) for step in parsed][:5]
        except Exception as exc:
            logger.warning("Falha ao gerar/parsear plano (%s); a usar plano fixo.", exc)
            self.state.plan = DEFAULT_PLAN[:]

        logger.info("Plano de execução: %s", self.state.plan)
        return self.state.plan

    # ------------------------------------------------------------------
    # Tool: fetch_data
    # ------------------------------------------------------------------
    @span(kind="TOOL", name="fetch_data")
    def fetch_data_tool(self) -> bool:
        """Obtém headcounts do domínio alvo (fixture ou Crustdata live).

        Em modo live, HTTP 429 (rate limit) é registado com o valor de
        Retry-After; o loop do run_agent usa esse valor no backoff.
        """
        attempts = self.state.task_attempts.get("FETCH_DATA", 0)

        # Simulação de falha de rede na 1.ª tentativa (modo demo).
        if self.fixture_mode and self.inject_fault and attempts == 1:
            error_msg = "Simulated Network Timeout Anomaly"
            self.state.errors_log.append(
                {"step": "FETCH_DATA", "attempt": attempts, "error": error_msg}
            )
            logger.warning("[%d/%d] %s", attempts, self.max_retries, error_msg)
            return False

        # Dados sintéticos de demonstração.
        if self.fixture_mode:
            self.state.evidence_ledger.append(
                {
                    "source": "fixture",
                    "company_domain": self.target_domain,
                    "current_headcount": 140,
                    "previous_headcount": 100,
                }
            )
            self.state.findings["current_headcount"] = 140
            self.state.findings["previous_headcount"] = 100
            logger.info("Dados fixture carregados para %s.", self.target_domain)
            return True

        # Modo live: Crustdata API (token via header Authorization).
        api_key = os.getenv("CRUSTDATA_API_KEY", "").strip()
        if not api_key:
            self.state.errors_log.append(
                {
                    "step": "FETCH_DATA",
                    "attempt": attempts,
                    "error": "CRUSTDATA_API_KEY em falta no modo live.",
                }
            )
            logger.error("CRUSTDATA_API_KEY em falta; a abortar fetch live.")
            return False

        url = (
            f"{os.getenv('CRUSTDATA_API_URL', 'https://api.crustdata.com')}"
            "/company/growth_metrics"
        )
        headers = {
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        }
        payload = {"company_domain": self.target_domain}

        resp = None
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.HTTPError as exc:
            error_entry = {
                "step": "FETCH_DATA",
                "attempt": attempts,
                "error": str(exc),
            }
            if resp is not None and resp.status_code == 429:
                retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                if retry_after is not None:
                    error_entry["retry_after"] = retry_after
            self.state.errors_log.append(error_entry)
            logger.error("Falha real na Crustdata: %s", exc)
            return False
        except Exception as exc:
            self.state.errors_log.append(
                {"step": "FETCH_DATA", "attempt": attempts, "error": str(exc)}
            )
            logger.error("Falha real na Crustdata: %s", exc)
            return False

        # Extração defensiva de dicionários imbricados.
        current = None
        previous = None
        growth_pct = None
        nested = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(nested, dict):
            current = nested.get("current_headcount", nested.get("headcount_current"))
            previous = nested.get("previous_headcount", nested.get("headcount_previous"))
            growth_pct = nested.get("growth_percentage", nested.get("growth_pct"))

        # Matemática reversa: se a API devolver apenas a % e um dos lados.
        if growth_pct is not None and growth_pct <= -100.0:
            self.state.errors_log.append(
                {
                    "step": "FETCH_DATA",
                    "attempt": attempts,
                    "error": (
                        "Crescimento impossível (growth_pct <= -100.0); "
                        "headcount não pode ser zero/negativo."
                    ),
                }
            )
            logger.error(
                "Crescimento impossível recebido da API (%.1f%%).", growth_pct
            )
            return False
        if growth_pct is not None and previous is None and current is not None:
            previous = current / (1.0 + growth_pct / 100.0)
        if growth_pct is not None and current is None and previous is not None:
            current = previous * (1.0 + growth_pct / 100.0)

        if current is None or previous is None:
            self.state.errors_log.append(
                {
                    "step": "FETCH_DATA",
                    "attempt": attempts,
                    "error": "Resposta da Crustdata sem headcounts utilizáveis.",
                }
            )
            return False

        self.state.evidence_ledger.append(
            {
                "source": "crustdata_live",
                "company_domain": self.target_domain,
                "current_headcount": current,
                "previous_headcount": previous,
            }
        )
        self.state.findings["current_headcount"] = current
        self.state.findings["previous_headcount"] = previous
        return True

    # ------------------------------------------------------------------
    # Análise de sinais (passo ANALYZE_SIGNALS)
    # ------------------------------------------------------------------
    def _analyze_signals(self) -> bool:
        curr = self.state.findings.get("current_headcount")
        prev = self.state.findings.get("previous_headcount")
        if curr is None or prev is None or prev == 0:
            self.state.errors_log.append(
                {"step": "ANALYZE_SIGNALS", "error": "Headcounts em falta."}
            )
            return False
        growth_pct = ((curr - prev) / prev) * 100.0
        self.state.findings["growth_pct"] = growth_pct
        self.state.findings["growth_string"] = f"{growth_pct:+.1f}%"
        logger.info("Sinais analisados: %s", self.state.findings["growth_string"])
        return True

    # ------------------------------------------------------------------
    # Verificação
    # ------------------------------------------------------------------
    def verify_metrics_gate(self) -> bool:
        """Recalcula a matemática do zero e compara com o growth_string."""
        curr = self.state.findings.get("current_headcount")
        prev = self.state.findings.get("previous_headcount")
        expected = self.state.findings.get("growth_string")
        if curr is None or prev is None or expected is None or prev == 0:
            self.state.is_verified = False
            return False

        recomputed = f"{((curr - prev) / prev) * 100.0:+.1f}%"
        self.state.is_verified = recomputed == expected
        logger.info(
            "Gate de verificação: esperado=%s recalculado=%s -> %s",
            expected,
            recomputed,
            self.state.is_verified,
        )
        return self.state.is_verified

    # ------------------------------------------------------------------
    # Avaliação de risco
    # ------------------------------------------------------------------
    def assess_risk(self) -> str:
        """Classifica o risco a partir do crescimento de headcount."""
        growth_pct = self.state.findings.get("growth_pct", 0.0)
        if growth_pct >= 25.0:
            self.state.risk_level = "HIGH"
        elif growth_pct >= 10.0:
            self.state.risk_level = "MEDIUM"
        else:
            self.state.risk_level = "LOW"
        logger.info(
            "Risco avaliado: %s (crescimento %.1f%%)",
            self.state.risk_level,
            growth_pct,
        )
        return self.state.risk_level

    # ------------------------------------------------------------------
    # Relatório (passo RENDER_REPORT)
    # ------------------------------------------------------------------
    def _render_report(self) -> str:
        """Gera relatório executivo via Bedrock; fallback offline determinístico."""
        growth = self.state.findings.get("growth_string", "n/d")
        risk = self.state.risk_level
        verified = self.state.is_verified
        report_prompt = (
            "És um analista sénior de Competitive Intelligence a escrever para um fundo de "
            "Venture Capital ou equipa de Corporate Development.\n"
            "Dados disponíveis:\n"
            "- Domínio analisado: {target_domain}\n"
            "- Crescimento de headcount: {growth}\n"
            "- Nível de risco de disrupção: {risk}\n"
            "- Verificação matemática: {verified}\n"
            "- Objetivo original: {goal}\n"
            "Escreve um relatório executivo curto (máximo 110 palavras) com esta estrutura exata:\n"
            "1. Sinal principal (1 frase)\n"
            "2. Interpretação (2-3 frases)\n"
            "3. Recomendação acionável clara (1-2 frases)\n"
            "Regras:\n"
            "- Tom profissional, direto e objetivo\n"
            "- Não inventes dados\n"
            "- Não uses linguagem promocional\n"
            "- Foca-te no que o crescimento de headcount pode significar estrategicamente"
        ).format(
            target_domain=self.target_domain,
            growth=growth,
            risk=risk,
            verified=verified,
            goal=self.goal,
        )

        try:
            report = self.call_bedrock(report_prompt, max_tokens=512)
        except Exception as exc:
            logger.warning("Bedrock indisponível (%s); relatório offline.", exc)
            report = (
                f"SINAL PRINCIPAL: {self.target_domain} registou {growth} de crescimento "
                f"de headcount.\n"
                f"INTERPRETAÇÃO: O ritmo de contratação sugere uma fase de expansão "
                f"agressiva. Risco de disrupção avaliado como {risk}.\n"
                f"RECOMENDAÇÃO: Monitorizar movimentos de talento e intensidade de "
                f"recrutamento nas próximas semanas."
            )

        self.state.final_report = report
        logger.info("Relatório gerado (%d caracteres).", len(report))
        return report

    # ------------------------------------------------------------------
    # Execução de um passo
    # ------------------------------------------------------------------
    def _execute_step(self, step: str) -> bool:
        if step == "FETCH_DATA":
            return self.fetch_data_tool()
        if step == "ANALYZE_SIGNALS":
            return self._analyze_signals()
        if step == "VERIFY_METRICS":
            return self.verify_metrics_gate()
        if step == "ASSESS_RISK":
            self.assess_risk()
            return True
        if step == "RENDER_REPORT":
            self._render_report()
            return True
        return True

    # ------------------------------------------------------------------
    # Loop principal
    # ------------------------------------------------------------------
    @span(kind="AGENT", name="run_agent")
    def run_agent(self) -> RunState:
        """Orquestra o plano de forma sequencial com retries e backoff.

        Se o estado já veio de um checkpoint (resume), o plano e o índice
        atual são preservados e a execução continua de onde parou.
        O backoff respeita Retry-After em erros HTTP 429 (teto de 30s).
        """
        logger.info("Objetivo: %s | Alvo: %s", self.goal, self.target_domain)
        if not self.state.plan:
            self.build_plan()
            self.state.save_checkpoint()
        else:
            logger.info("Plano já carregado do checkpoint: %s", self.state.plan)

        while self.state.current_step_idx < len(self.state.plan):
            step = self.state.plan[self.state.current_step_idx]
            attempts = self.state.task_attempts.get(step, 0) + 1
            self.state.task_attempts[step] = attempts

            if attempts > self.max_retries:
                logger.error("Limite de retries atingido em %s; a avançar.", step)
                self.state.current_step_idx += 1
                continue

            logger.info("Passo %s (tentativa %d/%d)", step, attempts, self.max_retries)
            ok = self._execute_step(step)
            if ok:
                self.state.current_step_idx += 1
                self.state.save_checkpoint()
            else:
                delay = min(1.5 * attempts, 10.0)
                last_error = next(
                    (
                        e
                        for e in reversed(self.state.errors_log)
                        if e.get("step") == step
                    ),
                    None,
                )
                if last_error and last_error.get("retry_after") is not None:
                    delay = min(float(last_error["retry_after"]), 30.0)
                logger.warning("Falha em %s; backoff de %.1fs.", step, delay)
                time.sleep(delay)

        self.state.save_checkpoint()
        logger.info("Execução concluída. Relatório: %s", self.state.final_report[:80])
        return self.state


def send_trace_v1(state: RunState, target_domain: str) -> None:
    """Envia um trace único para o endpoint /v1/trace do neatlogs.

    O destino é configurável por NEATLOGS_ENDPOINT (default
    https://ingest.neatlogs.com/). O endpoint /api/data/v2 do SDK 1.1.8 está
    descontinuado (404 confirmado); o transporte real da plataforma é o POST
    /v1/trace com um objeto JSON aninhado (children). Uma POST por execução,
    nunca por span.
    """
    api_key = os.getenv("NEATLOGS_API_KEY", "").strip()
    if not api_key:
        logger.warning("NEATLOGS_API_KEY em falta; trace não enviado.")
        return

    base_url = os.getenv(
        "NEATLOGS_ENDPOINT", "https://ingest.neatlogs.com/"
    ).rstrip("/")
    url = f"{base_url}/v1/trace"

    children = []
    for step in state.plan:
        child = {
            "name": step.lower(),
            "kind": "TOOL",
            "tool_name": step.lower(),
            "input": {"target_domain": target_domain},
        }
        if step == "FETCH_DATA":
            child["output"] = {
                "current_headcount": state.findings.get("current_headcount"),
                "previous_headcount": state.findings.get("previous_headcount"),
            }
            step_errors = [
                e for e in state.errors_log if e.get("step") == "FETCH_DATA"
            ]
            if step_errors:
                child["logs"] = [
                    {"level": "warning", "message": e.get("error", "")}
                    for e in step_errors
                ]
        elif step == "ANALYZE_SIGNALS":
            child["output"] = {"growth_pct": state.findings.get("growth_pct")}
        elif step == "VERIFY_METRICS":
            child["output"] = {"verified": state.is_verified}
        elif step == "ASSESS_RISK":
            child["output"] = {"risk_level": state.risk_level}
        elif step == "RENDER_REPORT":
            child["output"] = {"report": state.final_report[:200]}
        children.append(child)

    trace = {
        "name": "disrupt-radar",
        "kind": "WORKFLOW",
        "input": {"goal": state.goal, "target_domain": target_domain},
        "output": {
            "risk_level": state.risk_level,
            "verified": state.is_verified,
            "report": state.final_report[:500],
        },
        "children": children,
    }

    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=trace,
            timeout=15,
        )
        if resp.status_code == 200:
            body = resp.json()
            logger.info(
                "Trace enviado: %s (%s spans)",
                body.get("trace_id"),
                body.get("spans"),
            )
        else:
            logger.warning(
                "Falha ao enviar trace: %s %s", resp.status_code, resp.text[:200]
            )
    except Exception as exc:
        logger.warning("Falha ao enviar trace: %s", exc)


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="DisruptRadar — agente de inteligência competitiva via headcount."
    )
    parser.add_argument(
        "--goal",
        default=(
            "Detetar disrupções competitivas num domínio alvo usando crescimento "
            "de headcount."
        ),
        help="objetivo do agente (default: deteção de disrupção por headcount)",
    )
    parser.add_argument(
        "--domain",
        default="openai.com",
        help="domínio alvo (default: openai.com)",
    )
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="usa dados sintéticos, sem rede (RUN_DEMO_FIXTURE_MODE=true)",
    )
    parser.add_argument(
        "--fault",
        action="store_true",
        help="injeta falha simulada na 1.ª tentativa (INJECT_LOCAL_FAULT_SIMULATION=true)",
    )
    parser.add_argument(
        "--resume",
        type=int,
        default=None,
        metavar="RUN_ID",
        help="restaura artifacts/checkpoint_<RUN_ID>.json e continua de onde parou",
    )
    args = parser.parse_args()

    try:
        if args.resume is not None:
            restored = RunState.load_checkpoint(args.resume)
            agent_instance = DisruptRadarAgent(
                goal=restored.goal or args.goal,
                target_domain=restored.target_domain or args.domain,
                fixture_mode=True if args.fixture else None,
                inject_fault=True if args.fault else None,
                state=restored,
            )
            logger.info(
                "Checkpoint %s restaurado (passo %d/%d).",
                args.resume,
                restored.current_step_idx + 1,
                len(restored.plan) or 1,
            )
        else:
            agent_instance = DisruptRadarAgent(
                goal=args.goal,
                target_domain=args.domain,
                fixture_mode=True if args.fixture else None,
                inject_fault=True if args.fault else None,
            )
    except ValueError as exc:
        print(f"Erro: {exc}")
        raise SystemExit(2)
    except FileNotFoundError:
        print(f"Checkpoint não encontrado: artifacts/checkpoint_{args.resume}.json")
        raise SystemExit(2)

    final_state = agent_instance.run_agent()
    send_trace_v1(final_state, agent_instance.target_domain)
    print("\n===== RELATÓRIO FINAL =====\n")
    print(final_state.final_report)
    print(f"\nRisco: {final_state.risk_level} | Verificado: {final_state.is_verified}")