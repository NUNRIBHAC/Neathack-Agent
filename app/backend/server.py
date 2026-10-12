from dotenv import load_dotenv
load_dotenv()

import os
import uuid
import asyncio
from datetime import datetime, timezone, timedelta

import jwt
import bcrypt
import httpx
from html import escape as escape_html
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from motor.motor_asyncio import AsyncIOMotorClient
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import agent_core
import emailer
import billing

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALG = "HS256"

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="DisruptRadar API")
api = APIRouter(prefix="/api")

scheduler = AsyncIOScheduler()


# ---------- helpers ----------
def now():
    return datetime.now(timezone.utc)


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_password(p: str, h: str) -> bool:
    return bcrypt.checkpw(p.encode(), h.encode())


def create_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email, "exp": now() + timedelta(days=7), "type": "access"}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


async def get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.cookies.get("access_token")
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
    user = await db.users.find_one({"_id": payload["sub"]})
    if not user:
        raise HTTPException(401, "User not found")
    user.pop("password_hash", None)
    return user


async def require_workspace(workspace_id: str, user: dict) -> dict:
    ws = await db.workspaces.find_one({"_id": workspace_id})
    if not ws:
        raise HTTPException(404, "Workspace not found")
    member = await db.memberships.find_one({"workspace_id": workspace_id, "user_id": user["_id"]})
    if not member:
        raise HTTPException(403, "Not a member of this workspace")
    return ws


PLAN_LIMITS = {"free": {"domains": 3, "cadence": "weekly"}, "pro": {"domains": 50, "cadence": "daily"}}


# ---------- models ----------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str = "Analyst"


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class WorkspaceIn(BaseModel):
    name: str


class WatchlistIn(BaseModel):
    domain: str
    tags: list[str] = []


class RunNowIn(BaseModel):
    workspace_id: str
    watchlist_item_id: str


class SettingsIn(BaseModel):
    slack_webhook: str = ""
    delta_threshold: float = 10.0
    cadence: str = "weekly"


class GoogleSessionIn(BaseModel):
    session_id: str


class InviteIn(BaseModel):
    email: EmailStr


class CheckoutIn(BaseModel):
    workspace_id: str


# ---------- auth routes ----------
async def _accept_pending_invites(uid: str, email: str):
    """When a user signs up/in, auto-join any workspaces they were invited to."""
    pending = await db.invites.find({"email": email, "status": "pending"}).to_list(200)
    joined = 0
    for inv in pending:
        exists = await db.memberships.find_one({"workspace_id": inv["workspace_id"], "user_id": uid})
        if not exists:
            await db.memberships.insert_one({"_id": str(uuid.uuid4()), "workspace_id": inv["workspace_id"], "user_id": uid, "role": "member"})
            joined += 1
        await db.invites.update_one({"_id": inv["_id"]}, {"$set": {"status": "accepted", "accepted_at": now()}})
    return joined


@api.post("/auth/register")
async def register(body: RegisterIn):
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email already registered")
    uid = str(uuid.uuid4())
    await db.users.insert_one({
        "_id": uid, "email": email, "password_hash": hash_password(body.password),
        "name": body.name, "role": "user", "created_at": now(),
    })
    joined = await _accept_pending_invites(uid, email)
    wid = await _create_workspace(uid, f"{body.name}'s Workspace")
    token = create_token(uid, email)
    return {"token": token, "user": {"id": uid, "email": email, "name": body.name}, "default_workspace": wid, "joined_invites": joined}


@api.post("/auth/login")
async def login(body: LoginIn):
    email = body.email.lower()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    token = create_token(user["_id"], email)
    return {"token": token, "user": {"id": user["_id"], "email": email, "name": user.get("name")}}


@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return {"id": user["_id"], "email": user["email"], "name": user.get("name"), "role": user.get("role")}


@api.post("/auth/google/session")
async def google_session(body: GoogleSessionIn):
    """Exchange an Emergent OAuth session_id for our own app JWT."""
    url = os.environ["EMERGENT_OAUTH_SESSION_URL"]
    async with httpx.AsyncClient(timeout=20) as hc:
        resp = await hc.get(url, headers={"X-Session-ID": body.session_id})
    if resp.status_code != 200:
        raise HTTPException(401, "Invalid or expired Google session")
    data = resp.json()
    email = (data.get("email") or "").lower()
    if not email:
        raise HTTPException(401, "Google session returned no email")
    user = await db.users.find_one({"email": email})
    if not user:
        uid = str(uuid.uuid4())
        await db.users.insert_one({
            "_id": uid, "email": email, "password_hash": "", "name": data.get("name") or "Analyst",
            "role": "user", "picture": data.get("picture"), "provider": "google", "created_at": now(),
        })
        await _accept_pending_invites(uid, email)
        await _create_workspace(uid, f"{(data.get('name') or 'My')}'s Workspace")
        user = await db.users.find_one({"_id": uid})
    else:
        await _accept_pending_invites(user["_id"], email)
    token = create_token(user["_id"], email)
    return {"token": token, "user": {"id": user["_id"], "email": email, "name": user.get("name")}}


# ---------- workspace routes ----------
async def _create_workspace(uid: str, name: str) -> str:
    wid = str(uuid.uuid4())
    await db.workspaces.insert_one({"_id": wid, "name": name, "owner_id": uid, "plan": "free", "created_at": now()})
    await db.memberships.insert_one({"_id": str(uuid.uuid4()), "workspace_id": wid, "user_id": uid, "role": "owner"})
    await db.settings.insert_one({"_id": str(uuid.uuid4()), "workspace_id": wid, "slack_webhook": "", "delta_threshold": 10.0, "cadence": "weekly"})
    return wid


@api.get("/workspaces")
async def list_workspaces(user: dict = Depends(get_current_user)):
    memberships = await db.memberships.find({"user_id": user["_id"]}).to_list(100)
    wids = [m["workspace_id"] for m in memberships]
    wss = await db.workspaces.find({"_id": {"$in": wids}}).to_list(100)
    out = []
    for w in wss:
        count = await db.watchlist_items.count_documents({"workspace_id": w["_id"]})
        out.append({"id": w["_id"], "name": w["name"], "plan": w.get("plan", "free"), "domain_count": count})
    return out


@api.post("/workspaces")
async def create_workspace(body: WorkspaceIn, user: dict = Depends(get_current_user)):
    wid = await _create_workspace(user["_id"], body.name)
    return {"id": wid, "name": body.name, "plan": "free", "domain_count": 0}


@api.get("/workspaces/{workspace_id}/settings")
async def get_settings(workspace_id: str, user: dict = Depends(get_current_user)):
    await require_workspace(workspace_id, user)
    s = await db.settings.find_one({"workspace_id": workspace_id}) or {}
    return {"slack_webhook": s.get("slack_webhook", ""), "delta_threshold": s.get("delta_threshold", 10.0), "cadence": s.get("cadence", "weekly")}


@api.put("/workspaces/{workspace_id}/settings")
async def update_settings(workspace_id: str, body: SettingsIn, user: dict = Depends(get_current_user)):
    await require_workspace(workspace_id, user)
    await db.settings.update_one({"workspace_id": workspace_id}, {"$set": body.model_dump()}, upsert=True)
    return {"ok": True}


@api.post("/workspaces/{workspace_id}/slack/test")
async def slack_test(workspace_id: str, user: dict = Depends(get_current_user)):
    await require_workspace(workspace_id, user)
    s = await db.settings.find_one({"workspace_id": workspace_id}) or {}
    webhook = s.get("slack_webhook")
    if not webhook:
        raise HTTPException(400, "No Slack webhook configured. Save one first.")
    try:
        import requests
        r = await asyncio.to_thread(
            lambda: requests.post(webhook, json={"text": ":satellite: *DisruptRadar* test alert — your Slack webhook is live. High-risk runs will post here automatically."}, timeout=8, allow_redirects=False)
        )
        if r.status_code >= 300 or r.text.strip() != "ok":
            raise HTTPException(400, f"Slack rejected the webhook ({r.status_code}). Check the URL.")
    except HTTPException:
        raise
    except Exception as e:  # noqa
        raise HTTPException(502, f"Could not reach Slack: {e}")
    return {"ok": True}


# ---------- watchlist routes ----------
@api.get("/workspaces/{workspace_id}/watchlist")
async def get_watchlist(workspace_id: str, user: dict = Depends(get_current_user)):
    await require_workspace(workspace_id, user)
    items = await db.watchlist_items.find({"workspace_id": workspace_id}).to_list(200)
    return [_serialize_item(i) for i in items]


@api.post("/workspaces/{workspace_id}/watchlist")
async def add_watchlist(workspace_id: str, body: WatchlistIn, user: dict = Depends(get_current_user)):
    ws = await require_workspace(workspace_id, user)
    limit = PLAN_LIMITS[ws.get("plan", "free")]["domains"]
    count = await db.watchlist_items.count_documents({"workspace_id": workspace_id})
    if count >= limit:
        raise HTTPException(402, f"Plan limit reached ({limit} domains). Upgrade to Pro for more.")
    domain = body.domain.strip().lower().replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]
    if not domain or "." not in domain:
        raise HTTPException(400, "Invalid domain")
    if await db.watchlist_items.find_one({"workspace_id": workspace_id, "domain": domain}):
        raise HTTPException(400, "Domain already in watchlist")
    iid = str(uuid.uuid4())
    await db.watchlist_items.insert_one({
        "_id": iid, "workspace_id": workspace_id, "domain": domain, "tags": body.tags,
        "created_at": now(), "last_run_at": None,
    })
    # backfill: prefer real Crustdata weekly timeseries, fall back to simulation
    history = await asyncio.to_thread(agent_core.real_backfill, domain)
    if not history:
        history = agent_core.backfill_history(domain)
    for h in history:
        await db.headcount_snapshots.insert_one({
            "_id": str(uuid.uuid4()), "watchlist_item_id": iid, "workspace_id": workspace_id,
            "domain": domain, "headcount": h["headcount"], "captured_at": h["captured_at"],
            "source": h.get("source", "backfill"),
        })
    item = await db.watchlist_items.find_one({"_id": iid})
    return _serialize_item(item)


@api.delete("/watchlist/{item_id}")
async def delete_watchlist(item_id: str, user: dict = Depends(get_current_user)):
    item = await db.watchlist_items.find_one({"_id": item_id})
    if not item:
        raise HTTPException(404, "Not found")
    await require_workspace(item["workspace_id"], user)
    await db.watchlist_items.delete_one({"_id": item_id})
    await db.headcount_snapshots.delete_many({"watchlist_item_id": item_id})
    await db.runs.delete_many({"watchlist_item_id": item_id})
    return {"ok": True}


def _serialize_item(i: dict) -> dict:
    return {
        "id": i["_id"], "workspace_id": i["workspace_id"], "domain": i["domain"],
        "tags": i.get("tags", []),
        "last_run_at": i["last_run_at"].isoformat() if i.get("last_run_at") else None,
    }


# ---------- run engine ----------
async def _execute_run(item: dict) -> dict:
    wid = item["workspace_id"]
    domain = item["domain"]
    run_id = str(uuid.uuid4())
    await db.runs.insert_one({
        "_id": run_id, "watchlist_item_id": item["_id"], "workspace_id": wid, "domain": domain,
        "status": "running", "created_at": now(), "stages": [], "trace_url": None,
    })

    # previous headcount from latest snapshot
    prev_snap = await db.headcount_snapshots.find({"watchlist_item_id": item["_id"]}).sort("captured_at", -1).to_list(1)
    prev_hc = prev_snap[0]["headcount"] if prev_snap else None

    # 24h shared cache by domain (reuse real crustdata headcount + signals)
    cache = None
    day_ago = now() - timedelta(hours=24)
    cached = await db.headcount_snapshots.find_one(
        {"domain": domain, "source": "crustdata", "captured_at": {"$gte": day_ago}, "signals": {"$exists": True}},
        sort=[("captured_at", -1)]
    )
    if cached:
        cache = {"total": cached["headcount"], "signals": cached.get("signals")}

    result = await asyncio.to_thread(agent_core.run_pipeline, domain, prev_hc, cache)

    snap_source = "crustdata" if "crustdata" in result["source"] else "simulation"
    await db.headcount_snapshots.insert_one({
        "_id": str(uuid.uuid4()), "watchlist_item_id": item["_id"], "workspace_id": wid,
        "domain": domain, "headcount": result["headcount"], "captured_at": now(),
        "source": snap_source, "signals": result["signals"],
    })
    await db.runs.update_one({"_id": run_id}, {"$set": {
        "status": "success", "stages": result["stages"], "trace_url": result["trace_url"],
        "headcount": result["headcount"], "prev_headcount": result["prev_headcount"],
        "delta_pct": result["delta_pct"], "risk": result["risk"], "source": result["source"],
        "signals": result["signals"], "disruption_score": result["disruption_score"],
        "report": result["report"], "duration_ms": result["duration_ms"], "finished_at": now(),
    }})
    await db.watchlist_items.update_one({"_id": item["_id"]}, {"$set": {"last_run_at": now()}})

    # alert — always fire Slack on HIGH risk, plus threshold breach
    settings = await db.settings.find_one({"workspace_id": wid}) or {}
    threshold = settings.get("delta_threshold", 10.0)
    if result["risk"] == "HIGH" or abs(result["delta_pct"]) >= threshold:
        await db.alerts.insert_one({
            "_id": str(uuid.uuid4()), "workspace_id": wid, "domain": domain, "run_id": run_id,
            "risk": result["risk"], "delta_pct": result["delta_pct"], "created_at": now(),
            "message": f"{domain}: {result['risk']} risk, headcount {result['delta_pct']:+.1f}%, disruption {result['disruption_score']}/100",
        })
        _maybe_slack(settings.get("slack_webhook"), domain, result)

    run = await db.runs.find_one({"_id": run_id})
    return _serialize_run(run)


def _maybe_slack(webhook: str, domain: str, result: dict):
    if not webhook:
        return
    try:
        import requests
        sig = result.get("signals") or {}
        hiring = sig.get("hiring") or {}
        funding = sig.get("funding") or {}
        requests.post(webhook, json={"text":
            f":rotating_light: *DisruptRadar* — *{domain}*: *{result['risk']}* risk\n"
            f"• Headcount {result['headcount']} ({result['delta_pct']:+.1f}%)\n"
            f"• Disruption score *{result.get('disruption_score')}/100*\n"
            f"• {hiring.get('openings') or 0} open roles · last funding {funding.get('last_round_type') or 'n/a'} ({funding.get('last_fundraise_date') or 'n/a'})"
        }, timeout=8)
    except Exception as e:  # noqa
        print(f"[slack] failed: {e}")


@api.post("/runs/run-now")
async def run_now(body: RunNowIn, user: dict = Depends(get_current_user)):
    await require_workspace(body.workspace_id, user)
    item = await db.watchlist_items.find_one({"_id": body.watchlist_item_id})
    if not item:
        raise HTTPException(404, "Watchlist item not found")
    return await _execute_run(item)


@api.get("/watchlist/{item_id}/runs")
async def item_runs(item_id: str, user: dict = Depends(get_current_user)):
    item = await db.watchlist_items.find_one({"_id": item_id})
    if not item:
        raise HTTPException(404, "Not found")
    await require_workspace(item["workspace_id"], user)
    runs = await db.runs.find({"watchlist_item_id": item_id}).sort("created_at", -1).to_list(50)
    return [_serialize_run(r) for r in runs]


@api.get("/watchlist/{item_id}/snapshots")
async def item_snapshots(item_id: str, user: dict = Depends(get_current_user)):
    item = await db.watchlist_items.find_one({"_id": item_id})
    if not item:
        raise HTTPException(404, "Not found")
    await require_workspace(item["workspace_id"], user)
    snaps = await db.headcount_snapshots.find({"watchlist_item_id": item_id}).sort("captured_at", 1).to_list(500)
    return [{"headcount": s["headcount"], "captured_at": s["captured_at"].isoformat(), "source": s.get("source")} for s in snaps]


@api.get("/watchlist/{item_id}")
async def item_detail(item_id: str, user: dict = Depends(get_current_user)):
    item = await db.watchlist_items.find_one({"_id": item_id})
    if not item:
        raise HTTPException(404, "Not found")
    await require_workspace(item["workspace_id"], user)
    latest = await _latest_run(item_id)
    return {**_serialize_item(item), "latest_run": latest}


def _serialize_run(r: dict) -> dict:
    return {
        "id": r["_id"], "domain": r["domain"], "status": r["status"],
        "created_at": r["created_at"].isoformat(), "stages": r.get("stages", []),
        "trace_url": r.get("trace_url"), "headcount": r.get("headcount"),
        "prev_headcount": r.get("prev_headcount"), "delta_pct": r.get("delta_pct"),
        "risk": r.get("risk"), "source": r.get("source"), "report": r.get("report"),
        "signals": r.get("signals"), "disruption_score": r.get("disruption_score"),
        "duration_ms": r.get("duration_ms"),
    }


async def _latest_run(item_id: str):
    runs = await db.runs.find({"watchlist_item_id": item_id, "status": "success"}).sort("created_at", -1).to_list(1)
    return _serialize_run(runs[0]) if runs else None


# ---------- dashboard ----------
@api.get("/workspaces/{workspace_id}/dashboard")
async def dashboard(workspace_id: str, user: dict = Depends(get_current_user)):
    await require_workspace(workspace_id, user)
    items = await db.watchlist_items.find({"workspace_id": workspace_id}).to_list(200)
    companies = []
    risk_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    for i in items:
        latest = await _latest_run(i["_id"])
        snaps = await db.headcount_snapshots.find({"watchlist_item_id": i["_id"]}).sort("captured_at", -1).to_list(1)
        headcount = (latest and latest.get("headcount")) or (snaps[0]["headcount"] if snaps else None)
        risk = latest.get("risk") if latest else None
        if risk in risk_counts:
            risk_counts[risk] += 1
        companies.append({
            "id": i["_id"], "domain": i["domain"], "tags": i.get("tags", []),
            "headcount": headcount, "delta_pct": latest.get("delta_pct") if latest else None,
            "risk": risk, "last_run_at": i["last_run_at"].isoformat() if i.get("last_run_at") else None,
            "trace_url": latest.get("trace_url") if latest else None,
            "disruption_score": latest.get("disruption_score") if latest else None,
        })
    alerts = await db.alerts.find({"workspace_id": workspace_id}).sort("created_at", -1).to_list(10)
    return {
        "companies": companies,
        "summary": {"total": len(items), "risk_counts": risk_counts,
                    "high_movers": sum(1 for c in companies if c["risk"] == "HIGH")},
        "alerts": [{"domain": a["domain"], "message": a["message"], "risk": a["risk"],
                    "created_at": a["created_at"].isoformat()} for a in alerts],
    }


# ---------- scheduler ----------
async def scheduled_poll():
    print("[scheduler] running poll cycle")
    settings = await db.settings.find({}).to_list(1000)
    for s in settings:
        items = await db.watchlist_items.find({"workspace_id": s["workspace_id"]}).to_list(200)
        for item in items:
            # lock: skip if run in last 20h
            recent = await db.runs.find_one({"watchlist_item_id": item["_id"], "created_at": {"$gte": now() - timedelta(hours=20)}})
            if recent:
                continue
            try:
                await _execute_run(item)
            except Exception as e:  # noqa
                print(f"[scheduler] run failed {item['domain']}: {e}")


@api.get("/")
async def root():
    return {"message": "DisruptRadar API online"}


# ---------- billing (Dodo Payments) ----------
@api.get("/billing/status")
async def billing_status(user: dict = Depends(get_current_user)):
    return {"configured": billing.is_configured()}


@api.post("/billing/checkout")
async def billing_checkout(body: CheckoutIn, user: dict = Depends(get_current_user)):
    ws = await require_workspace(body.workspace_id, user)
    if ws.get("owner_id") != user["_id"]:
        raise HTTPException(403, "Only the workspace owner can upgrade")
    if ws.get("plan") == "pro":
        raise HTTPException(409, "Workspace is already Pro")
    if not billing.is_configured():
        raise HTTPException(503, "Billing is not configured yet. Set the Dodo Pro product ID.")
    frontend = os.environ.get("FRONTEND_URL") or "https://intel-radar-1.preview.emergentagent.com"
    try:
        session = await billing.create_checkout(body.workspace_id, f"{frontend}/billing/return")
    except Exception as e:  # noqa
        raise HTTPException(502, f"Could not start checkout: {e}")
    return session


@api.post("/dodo/webhook/")
async def dodo_webhook(request: Request):
    raw = await request.body()
    headers = {
        "webhook-id": request.headers.get("webhook-id", ""),
        "webhook-signature": request.headers.get("webhook-signature", ""),
        "webhook-timestamp": request.headers.get("webhook-timestamp", ""),
    }
    try:
        payload = billing.verify_webhook(raw, headers)
    except Exception as e:  # noqa
        raise HTTPException(400, "Invalid webhook signature")
    event_id = headers["webhook-id"]
    event_type = payload.get("type")
    data = payload.get("data") or {}
    workspace_id = (data.get("metadata") or {}).get("workspace_id")
    try:
        await db.dodo_events.insert_one({"event_id": event_id, "type": event_type, "at": now()})
    except Exception as e:  # noqa
        if getattr(e, "code", None) == 11000:
            return {"ok": True, "duplicate": True}
        raise HTTPException(500, "Webhook storage failed")
    if event_type in {"payment.succeeded", "subscription.active"} and workspace_id:
        await db.workspaces.update_one(
            {"_id": workspace_id, "plan": {"$ne": "pro"}},
            {"$set": {"plan": "pro", "dodo_customer_id": data.get("customer_id"),
                      "dodo_subscription_id": data.get("subscription_id")}},
        )
        await db.subscriptions.update_one({"workspace_id": workspace_id}, {"$set": {
            "workspace_id": workspace_id, "status": "active", "plan": "pro", "updated_at": now()}}, upsert=True)
    elif event_type in {"subscription.cancelled", "subscription.expired"} and workspace_id:
        await db.workspaces.update_one({"_id": workspace_id}, {"$set": {"plan": "free"}})
        await db.subscriptions.update_one({"workspace_id": workspace_id}, {"$set": {"status": "cancelled", "plan": "free", "updated_at": now()}}, upsert=True)
    return {"ok": True}


# ---------- member invites ----------
@api.get("/workspaces/{workspace_id}/members")
async def list_members(workspace_id: str, user: dict = Depends(get_current_user)):
    await require_workspace(workspace_id, user)
    members = await db.memberships.find({"workspace_id": workspace_id}).to_list(200)
    out = []
    for m in members:
        u = await db.users.find_one({"_id": m["user_id"]})
        if u:
            out.append({"user_id": u["_id"], "email": u["email"], "name": u.get("name"), "role": m.get("role")})
    pending = await db.invites.find({"workspace_id": workspace_id, "status": "pending"}).to_list(200)
    return {"members": out, "pending": [{"email": p["email"], "id": p["_id"]} for p in pending]}


@api.post("/workspaces/{workspace_id}/invite")
async def invite_member(workspace_id: str, body: InviteIn, user: dict = Depends(get_current_user)):
    ws = await require_workspace(workspace_id, user)
    if ws.get("owner_id") != user["_id"]:
        raise HTTPException(403, "Only the owner can invite members")
    email = body.email.lower()
    existing = await db.users.find_one({"email": email})
    if existing:
        already = await db.memberships.find_one({"workspace_id": workspace_id, "user_id": existing["_id"]})
        if already:
            raise HTTPException(400, "User is already a member")
        await db.memberships.insert_one({"_id": str(uuid.uuid4()), "workspace_id": workspace_id, "user_id": existing["_id"], "role": "member"})
        status = "added"
    else:
        await db.invites.update_one(
            {"workspace_id": workspace_id, "email": email},
            {"$set": {"_id": str(uuid.uuid4()), "workspace_id": workspace_id, "email": email, "status": "pending", "invited_by": user["_id"], "created_at": now()}},
            upsert=True,
        )
        status = "pending"
    # notify by email (best-effort)
    try:
        html = (f'<table role="presentation" width="100%" style="max-width:520px;margin:0 auto;font-family:Arial,sans-serif;background:#10131E;border:1px solid #1E2436;border-radius:12px">'
                f'<tr><td style="padding:24px">'
                f'<h1 style="color:#F8FAFC;font-size:20px;margin:0 0 8px">You have been invited to {escape_html(ws["name"])}</h1>'
                f'<p style="color:#94A3B8;font-size:14px">{escape_html(user.get("name") or user["email"])} invited you to collaborate on the DisruptRadar watchlist. '
                f'Sign in to DisruptRadar with this email to join.</p>'
                f'<p style="color:#64748B;font-size:12px;margin-top:20px">Sent by DisruptRadar. We never ask for your password by email.</p>'
                f'</td></tr></table>')
        await emailer.send_email(email, f"You're invited to {ws['name']} on DisruptRadar", html)
    except Exception as e:  # noqa
        print(f"[invite] email failed: {e}")
    return {"status": status, "email": email}


@api.delete("/workspaces/{workspace_id}/members/{user_id}")
async def remove_member(workspace_id: str, user_id: str, user: dict = Depends(get_current_user)):
    ws = await require_workspace(workspace_id, user)
    if ws.get("owner_id") != user["_id"]:
        raise HTTPException(403, "Only the owner can remove members")
    if user_id == ws.get("owner_id"):
        raise HTTPException(400, "Cannot remove the owner")
    await db.memberships.delete_one({"workspace_id": workspace_id, "user_id": user_id})
    return {"ok": True}


# ---------- weekly digest ----------
async def _workspace_movers(workspace_id: str):
    items = await db.watchlist_items.find({"workspace_id": workspace_id}).to_list(200)
    movers = []
    for i in items:
        latest = await _latest_run(i["_id"])
        if latest:
            movers.append({"domain": i["domain"], "headcount": latest.get("headcount"),
                           "delta_pct": latest.get("delta_pct"), "risk": latest.get("risk")})
    movers.sort(key=lambda m: abs(m.get("delta_pct") or 0), reverse=True)
    return movers[:10]


@api.post("/workspaces/{workspace_id}/digest/send")
async def send_digest_now(workspace_id: str, user: dict = Depends(get_current_user)):
    ws = await require_workspace(workspace_id, user)
    movers = await _workspace_movers(workspace_id)
    html = emailer.build_digest_html(ws["name"], movers)
    try:
        eid = await emailer.send_email(user["email"], f"DisruptRadar weekly digest — {ws['name']}", html)
    except httpx.HTTPStatusError as e:
        try:
            info = e.response.json()
        except Exception:  # noqa
            info = {}
        return {"ok": False, "reason": info.get("message", "Email could not be sent"),
                "code": info.get("code"), "sent_to": user["email"], "movers": len(movers)}
    except Exception as e:  # noqa
        raise HTTPException(502, f"Email failed: {e}")
    return {"ok": True, "email_id": eid, "sent_to": user["email"], "movers": len(movers)}


async def weekly_digest_job():
    print("[digest] running weekly digest")
    workspaces = await db.workspaces.find({}).to_list(1000)
    for ws in workspaces:
        owner = await db.users.find_one({"_id": ws.get("owner_id")})
        if not owner or not owner.get("email"):
            continue
        movers = await _workspace_movers(ws["_id"])
        if not movers:
            continue
        try:
            html = emailer.build_digest_html(ws["name"], movers)
            await emailer.send_email(owner["email"], f"DisruptRadar weekly digest — {ws['name']}", html)
        except Exception as e:  # noqa
            print(f"[digest] failed for {ws['_id']}: {e}")


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.memberships.create_index([("workspace_id", 1), ("user_id", 1)])
    await db.headcount_snapshots.create_index([("watchlist_item_id", 1), ("captured_at", -1)])
    await db.runs.create_index([("watchlist_item_id", 1), ("created_at", -1)])
    # seed admin
    admin_email = os.environ.get("ADMIN_EMAIL")
    admin_pw = os.environ.get("ADMIN_PASSWORD")
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        uid = str(uuid.uuid4())
        await db.users.insert_one({"_id": uid, "email": admin_email, "password_hash": hash_password(admin_pw), "name": "Admin", "role": "admin", "created_at": now()})
        await _create_workspace(uid, "Fund I — Early Stage")
    scheduler.add_job(scheduled_poll, "interval", hours=24, id="daily_poll", replace_existing=True)
    scheduler.add_job(weekly_digest_job, "cron", day_of_week="mon", hour=13, id="weekly_digest", replace_existing=True)
    scheduler.start()


app.include_router(api)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)