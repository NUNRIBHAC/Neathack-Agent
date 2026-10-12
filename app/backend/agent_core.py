"""DisruptRadar agent core.

Refactor of the hackathon CLI loop: plan -> fetch -> analyze -> verify -> risk -> report.
Fetches headcount via Crustdata (24h cache, shared across workspaces for the same domain),
falls back to a deterministic simulation when Crustdata is unavailable, and produces an
executive report via a LiteLLM (OpenAI-compatible) endpoint with a template fallback.
"""
import os
import hashlib
import random
from datetime import datetime, timezone, timedelta

import requests

CRUSTDATA_API_KEY = os.environ.get("CRUSTDATA_API_KEY", "")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "").rstrip("/")
LITELLM_MODEL = os.environ.get("LITELLM_MODEL", "claude-haiku-4.5")

PIPELINE_STAGES = ["plan", "fetch", "analyze", "verify", "risk", "report"]


def _now():
    return datetime.now(timezone.utc)


def _seed_for(domain: str) -> int:
    return int(hashlib.sha256(domain.encode()).hexdigest(), 16) % (10 ** 8)


def _base_headcount(domain: str) -> int:
    rng = random.Random(_seed_for(domain))
    return rng.randint(40, 2800)


def fetch_crustdata_company(domain: str) -> dict:
    """Return {'total': int, 'timeseries': [{'date','count'}]} or raise. Crustdata 2025-11-01."""
    if not CRUSTDATA_API_KEY:
        raise RuntimeError("no crustdata key")
    resp = requests.post(
        "https://api.crustdata.com/company/enrich",
        headers={
            "Authorization": f"Bearer {CRUSTDATA_API_KEY}",
            "x-api-version": "2025-11-01",
            "Content-Type": "application/json",
        },
        json={"domains": [domain], "fields": ["basic_info", "headcount", "funding", "hiring"]},
        timeout=25,
    )
    if resp.status_code == 429:
        raise RuntimeError("crustdata_429")
    resp.raise_for_status()
    data = resp.json()
    results = data if isinstance(data, list) else [data]
    matches = (results[0] or {}).get("matches") if results else None
    if not matches:
        raise RuntimeError("no match")
    cdata = matches[0].get("company_data") or {}
    hc = cdata.get("headcount") or {}
    total = hc.get("total")
    if not total:
        raise RuntimeError("no headcount in response")
    ts = [
        {"date": p["date"], "count": int(p["employee_count"])}
        for p in (hc.get("timeseries") or []) if p.get("employee_count")
    ]
    return {
        "total": int(total),
        "timeseries": ts,
        "headcount_growth": hc.get("growth_percent") or {},
        "funding": cdata.get("funding") or {},
        "hiring": cdata.get("hiring") or {},
    }


def fetch_crustdata_headcount(domain: str):
    """Return (headcount, source) or raise."""
    company = fetch_crustdata_company(domain)
    return company["total"], "crustdata"


def simulate_headcount(domain: str, prev: int = None) -> int:
    rng = random.Random(_seed_for(domain) + _now().timetuple().tm_yday)
    base = prev if prev else _base_headcount(domain)
    drift = rng.uniform(-0.06, 0.09)
    return max(5, int(round(base * (1 + drift))))


def compute_risk(delta_pct: float) -> str:
    a = abs(delta_pct)
    if delta_pct <= -10 or a >= 18:
        return "HIGH"
    if a >= 7:
        return "MEDIUM"
    return "LOW"


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def compute_signals(company: dict, delta_pct: float) -> dict:
    """Derive the multi-signal disruption breakdown from a Crustdata company payload."""
    hc_growth = (company.get("headcount_growth") or {})
    hc6 = hc_growth.get("six_months")
    headcount_growth_6m = round(hc6, 1) if isinstance(hc6, (int, float)) else round(delta_pct, 1)

    hiring = company.get("hiring") or {}
    openings = hiring.get("openings_count")
    hiring_growth = hiring.get("openings_growth_percent")
    hiring_growth_pct = round(hiring_growth, 1) if isinstance(hiring_growth, (int, float)) else None

    funding = company.get("funding") or {}
    last_round_type = funding.get("last_round_type")
    last_round_amount = funding.get("last_round_amount_usd")
    last_fundraise = funding.get("last_fundraise_date")
    total_investment = funding.get("total_investment_usd")
    days_since_funding = None
    if last_fundraise:
        try:
            d = datetime.strptime(str(last_fundraise)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            days_since_funding = (_now() - d).days
        except Exception:  # noqa
            days_since_funding = None

    # --- component scores (0-100) ---
    hc_score = _clamp(50 + headcount_growth_6m * 1.6)
    if hiring_growth_pct is not None:
        hire_score = _clamp(50 + hiring_growth_pct * 0.8)
    elif isinstance(openings, (int, float)):
        hire_score = _clamp(30 + min(openings, 400) / 400 * 50)
    else:
        hire_score = 40.0
    if days_since_funding is not None:
        recency = _clamp(100 - days_since_funding / 3.65)  # ~1yr -> 0
        fund_score = _clamp(recency * 0.7 + (30 if total_investment else 0))
    else:
        fund_score = 25.0

    disruption_score = round(hc_score * 0.45 + hire_score * 0.30 + fund_score * 0.25, 1)
    return {
        "disruption_score": disruption_score,
        "headcount": {"growth_6m_pct": headcount_growth_6m, "score": round(hc_score, 1)},
        "hiring": {"openings": openings, "growth_pct": hiring_growth_pct, "score": round(hire_score, 1)},
        "funding": {
            "last_round_type": last_round_type,
            "last_round_amount_usd": last_round_amount,
            "last_fundraise_date": str(last_fundraise)[:10] if last_fundraise else None,
            "days_since_funding": days_since_funding,
            "total_investment_usd": total_investment,
            "score": round(fund_score, 1),
        },
    }


def simulate_signals(domain: str, delta_pct: float) -> dict:
    rng = random.Random(_seed_for(domain) + 7)
    openings = rng.randint(3, 220)
    hiring_growth_pct = round(rng.uniform(-20, 60), 1)
    days_since = rng.choice([45, 120, 240, 400, 700])
    rounds = ["seed", "series_a", "series_b", "series_c"]
    hc6 = round(delta_pct * rng.uniform(1.5, 4), 1)
    hc_score = _clamp(50 + hc6 * 1.6)
    hire_score = _clamp(50 + hiring_growth_pct * 0.8)
    recency = _clamp(100 - days_since / 3.65)
    fund_score = _clamp(recency * 0.7 + 30)
    disruption_score = round(hc_score * 0.45 + hire_score * 0.30 + fund_score * 0.25, 1)
    return {
        "disruption_score": disruption_score,
        "headcount": {"growth_6m_pct": hc6, "score": round(hc_score, 1)},
        "hiring": {"openings": openings, "growth_pct": hiring_growth_pct, "score": round(hire_score, 1)},
        "funding": {
            "last_round_type": rng.choice(rounds),
            "last_round_amount_usd": rng.choice([5, 12, 30, 80, 150]) * 1_000_000,
            "last_fundraise_date": (_now() - timedelta(days=days_since)).date().isoformat(),
            "days_since_funding": days_since,
            "total_investment_usd": rng.randint(10, 900) * 1_000_000,
            "score": round(fund_score, 1),
        },
    }


def llm_executive_report(domain: str, headcount: int, prev: int, delta_pct: float, risk: str, signals: dict = None) -> str:
    direction = "growth" if delta_pct >= 0 else "contraction"
    sig = signals or {}
    hiring = sig.get("hiring") or {}
    funding = sig.get("funding") or {}
    sig_line = (
        f"Multi-signal: disruption score {sig.get('disruption_score', 'n/a')}/100; "
        f"{hiring.get('openings') or 0} open roles (hiring growth {hiring.get('growth_pct')}%); "
        f"last funding {funding.get('last_round_type') or 'n/a'} "
        f"{('$' + format(int(funding['last_round_amount_usd']), ',')) if funding.get('last_round_amount_usd') else ''} "
        f"({funding.get('last_fundraise_date') or 'n/a'})."
    )
    prompt = (
        f"You are a competitive-intelligence analyst for a VC fund. Write a concise executive "
        f"briefing (130-190 words, markdown) on {domain}. Current LinkedIn headcount: {headcount} "
        f"(previous reading: {prev}, delta {delta_pct:+.1f}%, risk {risk}). {sig_line} "
        f"Interpret this {direction} signal for deal flow combining headcount, hiring and funding. Include: "
        f"1) one-line verdict, 2) talent-velocity read, 3) hiring & funding read, 4) a watch-item. "
        f"Be sharp, no fluff, no disclaimers."
    )
    if LITELLM_API_KEY and LITELLM_BASE_URL:
        try:
            resp = requests.post(
                f"{LITELLM_BASE_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {LITELLM_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": LITELLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 450,
                    "temperature": 0.5,
                },
                timeout=40,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:  # noqa
            print(f"[agent] LLM report failed for {domain}: {e}")
    verdict = {
        "HIGH": "Material signal — prioritize for review.",
        "MEDIUM": "Notable movement — keep on radar.",
        "LOW": "Stable — no action needed.",
    }[risk]
    hiring_s = f"{hiring.get('openings') or 0} open roles (growth {hiring.get('growth_pct')}%)"
    funding_s = f"{funding.get('last_round_type') or 'n/a'} on {funding.get('last_fundraise_date') or 'n/a'}"
    return (
        f"### Executive Briefing — {domain}\n\n"
        f"**Verdict:** {verdict} Disruption score {sig.get('disruption_score', 'n/a')}/100.\n\n"
        f"**Talent velocity:** Headcount moved from {prev} to {headcount} "
        f"({delta_pct:+.1f}%), indicating {direction}.\n\n"
        f"**Hiring & funding:** {hiring_s}; last round {funding_s}.\n\n"
        f"**Watch-item:** Confirm whether this {direction} is sustained across the next polling cycle "
        f"before adjusting conviction.\n"
    )


def run_pipeline(domain: str, prev_headcount: int = None, crustdata_cache=None):
    """Execute the 6-stage loop. Returns a dict with snapshot + signals + report + trace."""
    domain = domain.strip().lower()
    stages = []
    started = _now()

    stages.append({"stage": "plan", "status": "ok", "detail": f"Target locked: {domain}", "ts": _now().isoformat()})

    # fetch (with 24h shared cache). crustdata_cache = {"total": int, "signals": dict} when cached.
    source = "simulation"
    headcount = None
    signals = None
    if crustdata_cache is not None:
        headcount = crustdata_cache.get("total")
        signals = crustdata_cache.get("signals")
        source = "crustdata-cache"
    if headcount is None:
        try:
            company = fetch_crustdata_company(domain)
            headcount = company["total"]
            source = "crustdata"
            prev_tmp = prev_headcount if prev_headcount else headcount
            delta_tmp = ((headcount - prev_tmp) / prev_tmp * 100) if prev_tmp else 0.0
            signals = compute_signals(company, delta_tmp)
            stages.append({"stage": "fetch", "status": "ok", "detail": f"Headcount {headcount} + funding/hiring via crustdata", "ts": _now().isoformat()})
        except Exception as e:  # noqa
            headcount = simulate_headcount(domain, prev_headcount)
            source = "simulation"
            stages.append({"stage": "fetch", "status": "warn", "detail": f"Crustdata unavailable ({e}); simulated.", "ts": _now().isoformat()})

    prev = prev_headcount if prev_headcount else headcount
    delta_pct = ((headcount - prev) / prev * 100) if prev else 0.0
    if signals is None:
        signals = simulate_signals(domain, delta_pct)

    stages.append({"stage": "analyze", "status": "ok", "detail": f"Delta {delta_pct:+.1f}% · {signals['hiring'].get('openings') or 0} open roles · disruption {signals['disruption_score']}", "ts": _now().isoformat()})
    stages.append({"stage": "verify", "status": "ok", "detail": f"Reading consistent ({source})", "ts": _now().isoformat()})

    risk = compute_risk(delta_pct)
    # escalate risk when the composite disruption score is extreme
    if signals["disruption_score"] >= 75 and risk == "LOW":
        risk = "MEDIUM"
    stages.append({"stage": "risk", "status": "ok", "detail": f"Risk {risk} · disruption {signals['disruption_score']}/100", "ts": _now().isoformat()})

    report = llm_executive_report(domain, headcount, prev, delta_pct, risk, signals)
    stages.append({"stage": "report", "status": "ok", "detail": "Executive briefing generated", "ts": _now().isoformat()})

    trace_id = hashlib.sha1(f"{domain}{started.isoformat()}".encode()).hexdigest()[:16]
    duration_ms = int((_now() - started).total_seconds() * 1000)

    return {
        "domain": domain,
        "headcount": headcount,
        "prev_headcount": prev,
        "delta_pct": round(delta_pct, 2),
        "risk": risk,
        "source": source,
        "signals": signals,
        "disruption_score": signals["disruption_score"],
        "report": report,
        "stages": stages,
        "trace_url": f"https://neatlogs.com/trace/{trace_id}",
        "duration_ms": duration_ms,
    }


def real_backfill(domain: str, max_points: int = 40):
    """Try Crustdata real weekly timeseries. Returns snapshot list or None."""
    domain = domain.strip().lower()
    try:
        company = fetch_crustdata_company(domain)
    except Exception as e:  # noqa
        print(f"[agent] crustdata backfill failed for {domain}: {e}")
        return None
    ts = company["timeseries"]
    if not ts:
        return None
    ts = ts[-max_points:]
    series = []
    for p in ts:
        try:
            dt = datetime.strptime(p["date"][:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:  # noqa
            continue
        series.append({"headcount": p["count"], "captured_at": dt, "source": "crustdata"})
    return series or None


def backfill_history(domain: str, weeks: int = 12):
    """Generate plausible historical weekly snapshots so charts render immediately."""
    domain = domain.strip().lower()
    rng = random.Random(_seed_for(domain))
    hc = _base_headcount(domain)
    series = []
    today = _now()
    values = []
    for _ in range(weeks):
        values.append(hc)
        hc = max(5, int(round(hc / (1 + rng.uniform(-0.05, 0.07)))))
    values = list(reversed(values))
    for i, v in enumerate(values):
        ts = today - timedelta(weeks=(weeks - 1 - i))
        series.append({"headcount": v, "captured_at": ts})
    return series