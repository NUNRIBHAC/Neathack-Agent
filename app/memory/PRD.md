# DisruptRadar SaaS — PRD

## Original problem statement
Transform a hackathon CLI into a web SaaS for competitive intelligence: users register domains in a per-workspace watchlist, an agent runs the plan→fetch→analyze→verify→risk→report loop (headcount signals), results land in a dashboard with risk badges, time-series, and executive briefings. Target: VCs / corporate dev / strategy teams.

## Architecture
- **Frontend**: React 19 + Vite + Tailwind v4 + shadcn/ui + Recharts. Dark "Obsidian" theme. JWT Bearer auth (localStorage `dr_token`).
- **Backend**: FastAPI, all routes under `/api`. Motor/MongoDB. APScheduler 24h poll job with per-item 20h lock.
- **Agent**: `agent_core.py` — `run_pipeline` (6 stages), Crustdata 2025-11-01 `/company/enrich` for headcount + real weekly timeseries, LiteLLM (claude-haiku-4.5) executive report, both with graceful fallbacks (simulation / template).
- **Collections**: users, workspaces, memberships, watchlist_items, runs, headcount_snapshots, alerts, settings.

## User personas
- VC/corporate-dev analyst tracking deal-flow targets.
- Competitive-intel/strategy lead monitoring competitor headcount.

## Core requirements (static)
- Email+password JWT auth, multi-tenant workspaces (owner + members).
- Watchlist CRUD with tags; Free plan = 3 domains, Pro = 50.
- Run on-demand; scheduler for cadence; risk classification LOW/MEDIUM/HIGH.
- Dashboard table, company detail with headcount time-series + executive briefing + run history + trace link.
- Slack webhook + delta threshold settings; alerts on HIGH / threshold breach.

## Implemented (2026-06)
- Auth (register/login/me), auto default workspace, workspace switcher + create.
- Watchlist add/remove with tags, plan-limit (402), duplicate/invalid validation.
- Real Crustdata headcount + weekly timeseries backfill (simulation fallback).
- Run-now pipeline with 6-stage trace, risk, delta, LiteLLM executive report, 24h shared domain cache.
- Dashboard (metrics, companies table, pipeline visual, alerts), company detail (Recharts area chart with 30D/90D/1Y/ALL, briefing, run history).
- Settings: Slack webhook, delta threshold, cadence (persisted). Alerts created + optional Slack post.
- APScheduler daily poll with optimistic lock.

## Implemented (2026-06 — iteration 2)
- **Dodopayments billing**: /billing/checkout (hosted checkout, owner-only), /dodo/webhook/ (signed, idempotent) flips workspace plan free↔pro; Pro unlocks 50 domains + daily. Settings "Upgrade to Pro" + /billing/return page. Needs DODO_PRO_PRODUCT_ID + webhook secret to go live (test mode wired).
- **Weekly digest**: Emergent-managed email (Resend proxy), build_digest_html, /digest/send manual trigger + Monday 13:00 cron job. Blocks undeliverable test addresses gracefully.
- **Google OAuth**: Emergent-managed login → /auth/google/session exchanges session_id for the app's own JWT; AuthCallback + #session_id routing; "Continue with Google" button.
- **Member invites**: /invite (owner-only; adds existing users, pends new emails + email notice), /members list, remove member. Settings Members card.

## Implemented (2026-06 — iteration 3)
- **Multi-signal v2**: agent now fetches headcount + hiring (open roles, hiring growth) + funding (last round type/amount/date, total investment) from Crustdata and computes a composite **disruption_score (0-100)** (45% headcount, 30% hiring, 25% funding recency). Stored on runs + snapshots; risk escalates to ≥MEDIUM when score ≥75. Shown as a Disruption column (ScoreBar) on the dashboard and a full signals panel on company detail. LLM briefing now incorporates all three signals.
- **Slack alerts (real)**: /slack/test posts a live test message (rejects invalid webhooks with 400, allow_redirects=False + body=='ok'); HIGH-risk runs auto-post enriched alerts (score, open roles, funding).
- **Invite-accept**: _accept_pending_invites auto-joins invited emails to the inviting workspace on register and Google login (idempotent; invite marked accepted). register returns joined_invites.
- **Dodo billing**: code ready; returns 503 until DODO_PRO_PRODUCT_ID + webhook secret are set (user to create product in Dodo test mode; webhook URL https://intel-radar-1.preview.emergentagent.com/api/dodo/webhook/).

## Backlog / remaining
- **P1**: Create Dodo Pro product (test) + webhook secret → set DODO_PRO_PRODUCT_ID / DODO_PAYMENTS_WEBHOOK_KEY → verify live test upgrade.
- **P2**: Split server.py into routers; move Slack posts to async httpx; invite-acceptance UX for brand-new signups; richer funding timeseries chart; news/reviews signals.

## Next tasks
- Wire real Dodo product/webhook and confirm Free→Pro upgrade end-to-end.