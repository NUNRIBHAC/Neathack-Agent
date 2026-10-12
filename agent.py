"""
DisruptRadar: Autonomous Competitor Intelligence Agent
======================================================
Built for neatHack 2026.

Monitors headcount growth signals for a target domain, analyzes hiring
velocity, verifies the indicator math and produces an executive report.

Execution modes:
- RUN_DEMO_FIXTURE_MODE=true          -> synthetic data, no network
- INJECT_LOCAL_FAULT_SIMULATION=true  -> injects a failure on the 1st attempt
- CLI: --fixture / --fault force the modes above without touching .env
- CLI: --resume <run_id> restores the checkpoint and continues where it stopped
- LLM: LiteLLM first (if LITELLM_API_KEY in .env), then Bedrock,
  then deterministic offline fallback
- Crustdata: Company Enrich (POST /company/enrich, Bearer token)
"""

import ast
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
# Configuration and Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("disrupt-radar")

try:
    if os.getenv("NEATLOGS_API_KEY"):
        neatlogs.init(api_key=os.getenv("NEATLOGS_API_KEY"), tags=["disrupt-radar"])
        logger.info("neatlogs initialized (tags=['disrupt-radar'])")
    else:
        logger.warning("NEATLOGS_API_KEY missing; telemetry disabled.")
except Exception as exc:
    logger.warning("neatlogs.init unavailable (%s); telemetry via logging.", exc)


def span(kind: str, name: str):
    """Native telemetry decorator via LLMTracker (start/end_llm_span).

    Without an initialized tracker (or in tests), the function runs without
    telemetry.
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
    """Converts Retry-After (seconds or HTTP date) into seconds, or None."""
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


# ---------------------------------------------------------------------------
# Crustdata API (Company Enrich)
# ---------------------------------------------------------------------------
CRUSTDATA_BASE = os.getenv(
    "CRUSTDATA_API_URL", "https://api.crustdata.com"
).rstrip("/")
CRUSTDATA_API_VERSION = "2025-11-01"


def crustdata_fetch_growth(domain: str) -> dict:
    """Returns headcount and growth for a domain via Company Enrich."""
    resp = requests.post(
        f"{CRUSTDATA_BASE}/company/enrich",
        headers={
            "authorization": f"Bearer {os.environ['CRUSTDATA_API_KEY']}",
            "content-type": "application/json",
            "x-api-version": CRUSTDATA_API_VERSION,
        },
        json={
            "domains": [domain],
            "exact_match": True,
            "fields": ["basic_info", "headcount"],
        },
        timeout=30,
    )
    resp.raise_for_status()
    credits_used = resp.headers.get("X-Credits-Used")
    payload = resp.json()
    if not payload or not payload[0].get("matches"):
        raise ValueError(f"No Crustdata match for {domain}")
    company = max(
        payload[0]["matches"], key=lambda m: m.get("confidence_score") or 0
    )["company_data"]
    hc = company.get("headcount") or {}
    growth = hc.get("growth_percent") or {}
    return {
        "name": (company.get("basic_info") or {}).get("name"),
        "primary_domain": (company.get("basic_info") or {}).get("primary_domain"),
        "crustdata_company_id": company.get("crustdata_company_id"),
        "headcount_total": hc.get("total"),
        "growth_percent_mom": growth.get("mom"),
        "growth_percent_qoq": growth.get("qoq"),
        "growth_percent_six_months": growth.get("six_months"),
        "growth_percent_yoy": growth.get("yoy"),
        "credits_used": credits_used,
    }


class RunState:
    """Persistent agent state, with atomic checkpoint."""

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
        """Persists state atomically: .tmp + os.replace()."""
        artifacts_dir = os.path.join(os.getcwd(), "artifacts")
        os.makedirs(artifacts_dir, exist_ok=True)
        final_path = os.path.join(artifacts_dir, f"checkpoint_{self.run_id}.json")
        tmp_path = f"{final_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, final_path)
        logger.info("Atomic checkpoint written to %s", final_path)
        return final_path

    @classmethod
    def load_checkpoint(cls, run_id: int) -> "RunState":
        """Restores a state persisted by save_checkpoint()."""
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
    """Autonomous competitive intelligence agent with failure recovery."""

    @staticmethod
    def _validate_domain(domain: str) -> str:
        """Validates the basic format of a domain (e.g. acme.example.com)."""
        if not isinstance(domain, str):
            raise ValueError(f"Invalid target_domain: {domain!r}")
        candidate = domain.strip().lower()
        if len(candidate) > 253:
            raise ValueError(f"target_domain too long: {domain!r}")
        hostname_re = re.compile(
            r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$"
        )
        if not hostname_re.match(candidate):
            raise ValueError(f"target_domain has invalid format: {domain!r}")
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
        self._from_checkpoint = state is not None
        if state is None:
            self.state.plan = DEFAULT_PLAN[:]
        self.state.target_domain = self.target_domain

        self.bedrock = boto3.client(
            service_name="bedrock-runtime",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )

    # ------------------------------------------------------------------
    # LLM inference (LiteLLM first, then Bedrock)
    # ------------------------------------------------------------------
    @span(kind="TOOL", name="call_bedrock")
    def call_bedrock(self, prompt: str, max_tokens: int = 1024) -> str:
        """Wraps model invocations via LiteLLM (if configured) or Bedrock.

        With LITELLM_API_KEY in .env, it first tries the LiteLLM proxy
        (OpenAI chat completions compatible API); on failure, it falls back to
        Bedrock. Callers (build_plan/_render_report) have offline fallback.
        """
        if os.getenv("LITELLM_API_KEY", "").strip():
            try:
                return self._call_litellm(prompt, max_tokens=max_tokens)
            except Exception as exc:
                logger.warning("LiteLLM unavailable (%s); trying Bedrock.", exc)

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

    def _call_litellm(self, prompt: str, max_tokens: int = 1024) -> str:
        """Calls a LiteLLM proxy (OpenAI chat completions compatible API)."""
        base_url = os.getenv(
            "LITELLM_BASE_URL", "https://litellm.vision.aivar.app"
        ).rstrip("/")
        model = os.getenv("LITELLM_MODEL_ID", "claude-sonnet-4.6")
        api_key = os.getenv("LITELLM_API_KEY", "").strip()
        resp = requests.post(
            f"{base_url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content.strip()

    # ------------------------------------------------------------------
    # Step normalization
    # ------------------------------------------------------------------
    def _normalize_step(self, step: Any) -> str:
        """Normalizes LLM-generated step strings to standard keys."""
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
    def _parse_plan_from_llm(self, raw: str) -> List[str]:
        """Extracts a list of steps from varied LLM responses.

        Tries, in order: code fences, {"plan": [...]} object, JSON array and
        ast.literal_eval (single quotes). Normalizes, deduplicates and
        validates.
        """
        if not raw or not raw.strip():
            raise ValueError("empty LLM response")
        text = raw.strip()

        # 1. Code fences: ```json ... ``` or ``` ... ```
        fence = re.search(
            r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE
        )
        if fence:
            text = fence.group(1).strip()

        # 2. Object with a plan key: {"plan": [...]} / {"steps": [...]}
        obj_match = re.search(
            r'\{\s*"(?:plan|steps)"\s*:\s*(\[.*\])\s*\}',
            text,
            re.DOTALL,
        )
        if obj_match:
            text = obj_match.group(1).strip()

        # 3. JSON array: from the first '[' to the last ']'
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]

        parsed = None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(text)
            except Exception:
                parsed = None

        if isinstance(parsed, dict):
            for key in ("plan", "steps"):
                if isinstance(parsed.get(key), list):
                    parsed = parsed[key]
                    break
            else:
                raise ValueError("object without a step list")
        if not isinstance(parsed, list) or not parsed:
            raise ValueError("plan is not a non-empty list")

        normalized = [self._normalize_step(step) for step in parsed][:5]
        seen = set()
        deduped = []
        for step in normalized:
            if step not in seen:
                seen.add(step)
                deduped.append(step)
        if len(deduped) < 2:
            raise ValueError(f"normalized plan too short: {deduped!r}")
        return deduped

    @span(kind="TOOL", name="build_plan")
    def build_plan(self) -> List[str]:
        """Delegates the plan to the LLM; falls back to fixed plan on failure."""
        plan_prompt = (
            "You are a specialized competitive intelligence planner.\n"
            "User goal: {goal}\n"
            "Target company/domain: {target_domain}\n"
            "Your only task is to return an execution plan as valid JSON.\n"
            "Mandatory rules:\n"
            "- Return ONLY a JSON array (no markdown, no explanations, no backticks)\n"
            "- Maximum of 5 steps\n"
            "- Prefer these step names: FETCH_DATA, ANALYZE_SIGNALS, VERIFY_METRICS, ASSESS_RISK, RENDER_REPORT\n"
            "- Keep steps short and technical\n"
            "- Respond in English\n"
            'Correct format example: ["FETCH_DATA", "ANALYZE_SIGNALS", "VERIFY_METRICS", "ASSESS_RISK", "RENDER_REPORT"]'
        ).format(goal=self.goal, target_domain=self.target_domain)

        try:
            raw = self.call_bedrock(plan_prompt, max_tokens=512)
            self.state.plan = self._parse_plan_from_llm(raw)
        except Exception as exc:
            logger.warning("Failed to generate/parse plan (%s); using fixed plan.", exc)
            self.state.plan = DEFAULT_PLAN[:]

        logger.info("Execution plan: %s", self.state.plan)
        return self.state.plan

    # ------------------------------------------------------------------
    # Tool: fetch_data
    # ------------------------------------------------------------------
    @span(kind="TOOL", name="fetch_data")
    def fetch_data_tool(self) -> bool:
        """Fetches headcounts for the target domain (fixture or live Crustdata).

        Live mode uses the real Company Enrich (POST /company/enrich, Bearer
        token): `crustdata_fetch_growth()` returns `headcount.total` and the
        6-month growth (fallback: 12m), and `previous_headcount` is derived by
        reverse math: prev = current / (1 + growth/100). On HTTP 429 (rate
        limit), Retry-After is recorded and used in the backoff.
        """
        attempts = self.state.task_attempts.get("FETCH_DATA", 0)

        # Simulated network failure on the 1st attempt (demo mode).
        if self.fixture_mode and self.inject_fault and attempts == 1:
            error_msg = "Simulated Network Timeout Anomaly"
            self.state.errors_log.append(
                {"step": "FETCH_DATA", "attempt": attempts, "error": error_msg}
            )
            logger.warning("[%d/%d] %s", attempts, self.max_retries, error_msg)
            return False

        # Synthetic demonstration data.
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
            logger.info("Fixture data loaded for %s.", self.target_domain)
            return True

        # Live mode: Crustdata API - Company Enrich (real documented endpoint).
        api_key = os.getenv("CRUSTDATA_API_KEY", "").strip()
        if not api_key:
            self.state.errors_log.append(
                {
                    "step": "FETCH_DATA",
                    "attempt": attempts,
                    "error": "CRUSTDATA_API_KEY missing in live mode.",
                }
            )
            logger.error("CRUSTDATA_API_KEY missing; aborting live fetch.")
            return False

        try:
            data = crustdata_fetch_growth(self.target_domain)
        except requests.exceptions.HTTPError as exc:
            error_entry = {
                "step": "FETCH_DATA",
                "attempt": attempts,
                "error": str(exc),
            }
            if exc.response is not None and exc.response.status_code == 429:
                retry_after = _parse_retry_after(
                    exc.response.headers.get("Retry-After")
                )
                if retry_after is not None:
                    error_entry["retry_after"] = retry_after
            self.state.errors_log.append(error_entry)
            logger.error("Live Crustdata failure: %s", exc)
            return False
        except Exception as exc:
            self.state.errors_log.append(
                {"step": "FETCH_DATA", "attempt": attempts, "error": str(exc)}
            )
            logger.error("Live Crustdata failure: %s", exc)
            return False

        # Fields from the real Company Enrich schema:
        #   headcount.total + headcount.growth_percent.{mom,qoq,six_months,yoy}
        current = data.get("headcount_total")
        growth_pct = data.get("growth_percent_six_months")
        if growth_pct is None:
            growth_pct = data.get("growth_percent_yoy")

        # Reverse math: derive the previous headcount from the current total
        # and the growth percentage returned by the API.
        previous = None
        if current is not None and growth_pct is not None:
            previous = current / (1.0 + growth_pct / 100.0)

        if growth_pct is not None and growth_pct <= -100.0:
            self.state.errors_log.append(
                {
                    "step": "FETCH_DATA",
                    "attempt": attempts,
                    "error": (
                        "Impossible growth (growth_pct <= -100.0); "
                        "headcount cannot be zero or negative."
                    ),
                }
            )
            logger.error("Impossible growth received from API (%.1f%%).", growth_pct)
            return False

        if current is None or previous is None:
            sample = json.dumps(data, ensure_ascii=False)[:500]
            self.state.errors_log.append(
                {
                    "step": "FETCH_DATA",
                    "attempt": attempts,
                    "error": (
                        "/company/enrich response without usable headcounts; "
                        f"sample: {sample}"
                    ),
                }
            )
            logger.error("Headcounts not found in the enrich response.")
            return False

        self.state.evidence_ledger.append(
            {
                "source": "crustdata_live",
                "company_domain": self.target_domain,
                "company_name": data.get("name"),
                "crustdata_company_id": data.get("crustdata_company_id"),
                "current_headcount": current,
                "previous_headcount": previous,
                "credits_used": data.get("credits_used"),
            }
        )
        self.state.findings["current_headcount"] = current
        self.state.findings["previous_headcount"] = previous
        return True

    # ------------------------------------------------------------------
    # Signal analysis (ANALYZE_SIGNALS step)
    # ------------------------------------------------------------------
    def _analyze_signals(self) -> bool:
        curr = self.state.findings.get("current_headcount")
        prev = self.state.findings.get("previous_headcount")
        if curr is None or prev is None or prev == 0:
            self.state.errors_log.append(
                {"step": "ANALYZE_SIGNALS", "error": "Headcounts missing."}
            )
            return False
        growth_pct = ((curr - prev) / prev) * 100.0
        self.state.findings["growth_pct"] = growth_pct
        self.state.findings["growth_string"] = f"{growth_pct:+.1f}%"
        logger.info("Signals analyzed: %s", self.state.findings["growth_string"])
        return True

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------
    def verify_metrics_gate(self) -> bool:
        """Recomputes the math from scratch and compares with growth_string."""
        curr = self.state.findings.get("current_headcount")
        prev = self.state.findings.get("previous_headcount")
        expected = self.state.findings.get("growth_string")
        if curr is None or prev is None or expected is None or prev == 0:
            self.state.is_verified = False
            return False

        recomputed = f"{((curr - prev) / prev) * 100.0:+.1f}%"
        self.state.is_verified = recomputed == expected
        logger.info(
            "Verification gate: expected=%s recomputed=%s -> %s",
            expected,
            recomputed,
            self.state.is_verified,
        )
        return self.state.is_verified

    # ------------------------------------------------------------------
    # Risk assessment
    # ------------------------------------------------------------------
    def assess_risk(self) -> str:
        """Classifies risk from headcount growth."""
        growth_pct = self.state.findings.get("growth_pct", 0.0)
        if growth_pct >= 25.0:
            self.state.risk_level = "HIGH"
        elif growth_pct >= 10.0:
            self.state.risk_level = "MEDIUM"
        else:
            self.state.risk_level = "LOW"
        logger.info(
            "Risk assessed: %s (growth %.1f%%)",
            self.state.risk_level,
            growth_pct,
        )
        return self.state.risk_level

    # ------------------------------------------------------------------
    # Report (RENDER_REPORT step)
    # ------------------------------------------------------------------
    def _render_report(self) -> str:
        """Generates executive report via LLM; deterministic offline fallback."""
        growth = self.state.findings.get("growth_string", "n/a")
        risk = self.state.risk_level
        verified = self.state.is_verified
        report_prompt = (
            "You are a senior Competitive Intelligence analyst writing for a "
            "Venture Capital fund or Corporate Development team.\n"
            "Available data:\n"
            "- Analyzed domain: {target_domain}\n"
            "- Headcount growth: {growth}\n"
            "- Disruption risk level: {risk}\n"
            "- Math verification: {verified}\n"
            "- Original goal: {goal}\n"
            "Write a short executive report (max 110 words) with this exact structure:\n"
            "1. Main signal (1 sentence)\n"
            "2. Interpretation (2-3 sentences)\n"
            "3. Clear actionable recommendation (1-2 sentences)\n"
            "Rules:\n"
            "- Professional, direct and objective tone\n"
            "- Do not invent data\n"
            "- No promotional language\n"
            "- Focus on what headcount growth can mean strategically\n"
            "- Write the report in English"
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
            logger.warning("LLM unavailable (%s); offline report.", exc)
            growth_pct = self.state.findings.get("growth_pct", 0.0)
            if growth_pct >= 25.0:
                nuance = (
                    "The hiring pace is aggressive and consistent with an "
                    "accelerated expansion phase"
                )
            elif growth_pct >= 10.0:
                nuance = "The hiring pace is accelerating at a moderate rate"
            elif growth_pct >= 0.0:
                nuance = "Headcount is stable or growing slightly"
            else:
                nuance = (
                    "Headcount is contracting, which may indicate restructuring "
                    "or consolidation"
                )
            report = (
                f"MAIN SIGNAL: {self.target_domain} posted {growth} headcount growth.\n"
                f"INTERPRETATION: {nuance}. Disruption risk assessed as {risk}.\n"
                f"RECOMMENDATION: Monitor talent movement and hiring intensity "
                f"over the coming weeks."
            )

        self.state.final_report = report
        logger.info("Report generated (%d characters).", len(report))
        return report

    # ------------------------------------------------------------------
    # Step execution
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
    # Main loop
    # ------------------------------------------------------------------
    @span(kind="AGENT", name="run_agent")
    def run_agent(self) -> RunState:
        """Orchestrates the plan sequentially with retries and backoff.

        On fresh runs, the plan is generated by the LLM (build_plan). With
        resume, the plan and checkpoint index are preserved and execution
        continues where it stopped. Backoff respects Retry-After (cap 30s).
        """
        logger.info("Goal: %s | Target: %s", self.goal, self.target_domain)
        if not self._from_checkpoint:
            self.build_plan()
            self.state.save_checkpoint()
        else:
            logger.info("Plan already loaded from checkpoint: %s", self.state.plan)

        while self.state.current_step_idx < len(self.state.plan):
            step = self.state.plan[self.state.current_step_idx]
            attempts = self.state.task_attempts.get(step, 0) + 1
            self.state.task_attempts[step] = attempts

            if attempts > self.max_retries:
                logger.error("Retry limit reached at %s; moving on.", step)
                self.state.current_step_idx += 1
                continue

            logger.info("Step %s (attempt %d/%d)", step, attempts, self.max_retries)
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
                logger.warning("Failure at %s; backoff of %.1fs.", step, delay)
                time.sleep(delay)

        self.state.save_checkpoint()
        logger.info("Execution complete. Report: %s", self.state.final_report[:80])
        return self.state


def send_trace_v1(state: RunState, target_domain: str) -> None:
    """Sends a single trace to the neatlogs /v1/trace endpoint.

    The destination is configurable via NEATLOGS_ENDPOINT (default
    https://ingest.neatlogs.com/). The SDK 1.1.8 /api/data/v2 endpoint is
    deprecated (404 confirmed); the platform's real transport is POST
    /v1/trace with a nested JSON object (children). One POST per execution,
    never per span.
    """
    api_key = os.getenv("NEATLOGS_API_KEY", "").strip()
    if not api_key:
        logger.warning("NEATLOGS_API_KEY missing; trace not sent.")
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
                "Trace sent: %s (%s spans)",
                body.get("trace_id"),
                body.get("spans"),
            )
        else:
            logger.warning(
                "Failed to send trace: %s %s", resp.status_code, resp.text[:200]
            )
    except Exception as exc:
        logger.warning("Failed to send trace: %s", exc)


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="DisruptRadar - competitive intelligence agent via headcount."
    )
    parser.add_argument(
        "--goal",
        default=(
            "Detect competitive disruptions in a target domain using headcount "
            "growth."
        ),
        help="agent goal (default: headcount disruption detection)",
    )
    parser.add_argument(
        "--domain",
        default="openai.com",
        help="target domain (default: openai.com)",
    )
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="use synthetic data, no network (RUN_DEMO_FIXTURE_MODE=true)",
    )
    parser.add_argument(
        "--fault",
        action="store_true",
        help="inject simulated failure on the 1st attempt (INJECT_LOCAL_FAULT_SIMULATION=true)",
    )
    parser.add_argument(
        "--resume",
        type=int,
        default=None,
        metavar="RUN_ID",
        help="restore artifacts/checkpoint_<RUN_ID>.json and continue from where it stopped",
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
                "Checkpoint %s restored (step %d/%d).",
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
        print(f"Error: {exc}")
        raise SystemExit(2)
    except FileNotFoundError:
        print(f"Checkpoint not found: artifacts/checkpoint_{args.resume}.json")
        raise SystemExit(2)

    final_state = agent_instance.run_agent()
    send_trace_v1(final_state, agent_instance.target_domain)
    print("\n===== FINAL REPORT =====\n")
    print(final_state.final_report)
    print(f"\nRisk: {final_state.risk_level} | Verified: {final_state.is_verified}")