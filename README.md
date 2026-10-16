# Cloud AI Lead Generation & Sales Prospecting Agent

Production-oriented, cloud-hosted daily lead generation for local service businesses that may benefit from AI receptionists, appointment booking, lead capture, missed-call recovery, website chat, and automated follow-up.

**Stack choice (documented deviation from the prompt's example):** Python FastAPI + SQLAlchemy + APScheduler + Jinja2/static dashboard served by the *same* FastAPI service — no separate Next.js build. This is the simplest reliable single deployable service (one web+worker process on Render/Fly/Railway), with managed PostgreSQL in production via `DATABASE_URL` and SQLite fallback for local/dev only. Next.js can be layered on later against the same `/api/*` endpoints.

## Architecture

```
Scheduler (APScheduler, per-campaign cron, default 06:00 America/Los_Angeles)
  → Research runner (app/runner.py)
      Stage 1 Discover (provider adapters: Google Places, Yelp)
      Stage 2 Normalize + dedupe + verify (provider ID / phone / domain / name+address)
      Stage 3 Website audit (business's own site only) + opportunity evidence
      Stage 4 Explainable scoring (0–100, confidence tracked separately)
              + template sales brief (LLM optional, never required)
  → PostgreSQL (businesses, sources, evidence, audits, scores, runs, campaigns,
                 pipeline events, follow-ups, notifications, API usage, reports)
  → Dashboard (Overview / Leads / Lead detail / Campaigns / Pipeline / Jobs / Reports / Settings)
  → Daily report + optional email/Telegram notification (only when configured)
```

Pipeline: `DISCOVERED → NORMALIZED → VERIFIED → RESEARCHED → SCORED → QUALIFIED → READY_FOR_OUTREACH`, plus `INSUFFICIENT_DATA / DUPLICATE / OUT_OF_AREA / INACTIVE / DO_NOT_CONTACT`. Do-not-contact suppression is enforced and never reset by re-discovery.

**Honesty rules built in:** no provider key ⇒ the run is marked `failed` with “provider not configured” and *zero* leads are created. Nothing is ever fabricated — missing fields stay empty, `website not_found ≠ verified absent`, and industry assumptions are recorded as *potential* evidence, never proof a business misses calls or loses revenue. The synthetic provider exists only for tests (`APP_ENV=test`), labels every record `SYNTHETIC TEST …` / `is_test=true`, and cannot run in production.

## Industries (all six)

Roofing, junk removal, pressure washing, landscaping, HVAC, plumbing — each with its own search terms, opportunity signals, primary offer, and (for HVAC/plumbing) safety notes: never present an AI receptionist as a substitute for emergency services or technical diagnosis, and never guarantee emergency response times.

## Scoring (configurable defaults, prompt §9)

Industry fit 20 · Opportunity evidence 25 · Reputation 15 · Contact quality 15 · Geographic fit 10 · Sales accessibility 10 · Digital gaps 5. Tiers: 80+ High-priority, 60–79 Qualified, 40–59 Research further, 0–39 Low priority. Score and confidence are separate fields everywhere.

## Local run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # set ADMIN_PASSWORD; add provider keys to enable live discovery
.venv/bin/uvicorn app.main:app --port 8000
# open http://localhost:8000  (Basic auth: user admin, password = ADMIN_PASSWORD)
.venv/bin/python -m pytest tests/ -q
python migrations/001_initial.py   # versioned initial migration (app also create_all on first boot)
```

An example campaign (“Pomona — All Industries”) is seeded on first boot; edit/create campaigns via `POST /api/campaigns` or the Campaigns page — geography is never hardcoded in discovery logic.

## Environment variables

| Var | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | Prod | Managed PostgreSQL DSN (SQLite default locally) |
| `ADMIN_PASSWORD` | Prod | Dashboard/API auth (Basic `admin:<pw>` or `X-API-Token`); app refuses production traffic without it |
| `SECRET_KEY` | Prod | Session signing |
| `GOOGLE_PLACES_API_KEY` | For live Google discovery | Google Places API (New) |
| `YELP_API_KEY` | For live Yelp discovery | Yelp Fusion API |
| `OPENAI_API_KEY` + `LLM_PROVIDER` | No | Optional LLM polish hook only; templates work without it |
| `SMTP_URL`, `NOTIFICATION_EMAIL` | No | Daily-report email (recorded as skipped when unconfigured) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | No | Telegram notifications |
| `APP_ENV` | — | `development` / `test` / `production` |
| `DEFAULT_TIMEZONE` | No | Default `America/Los_Angeles` |

Secrets are server-side only: `/api/settings` and the Settings page return *configured / not_configured*, never values.

## Deployment

**Render (included `render.yaml` + `Dockerfile`):**
1. Push this repo to GitHub, create a Blueprint from `render.yaml` (creates the web service + `lead-gen-db` Postgres).
2. In the Render dashboard set the secret env vars marked `sync: false` (`ADMIN_PASSWORD`, `GOOGLE_PLACES_API_KEY`, `YELP_API_KEY`).
3. Deploy; verify `GET /health`, log in, trigger a manual run from a campaign, confirm the daily 06:00 PT job appears under Jobs.

**Fly.io:** `fly launch --dockerfile Dockerfile`, `fly postgres create` + `fly postgres attach`, `fly secrets set ADMIN_PASSWORD=… GOOGLE_PLACES_API_KEY=…`, `fly deploy`. Keep `min_machines_running = 1` so the in-process scheduler stays alive.

**Railway:** New project → Deploy from repo (Dockerfile detected) → add PostgreSQL plugin → set the same env vars in the service → deploy. Keep one always-on replica.

> Known scheduler caveat: APScheduler runs in-process in the single service (simplest reliable topology at this scale). Idempotent scheduled `run_key` (campaign + date) prevents duplicate runs after restarts/deploys. For multi-replica deployments, run exactly one scheduler replica or move scheduling to the platform cron hitting `POST /api/campaigns/{id}/run`.

## Estimated operating costs (estimates, not quotes)

- Hosting: Render Starter web (~$7/mo) + Basic Postgres (~$6/mo) — or Fly/Railway similar (~$5–15/mo total).
- Google Places Text Search: ~$0.032/request (app-tracked in `api_usage`); at 6 industries × 5 cities × 30 days ≈ 900 requests/mo ≈ ~$29/mo worst case before dedupe/budget caps — the default $5/day / $100/month campaign caps stop optional work first.
- Yelp Fusion: free tier historically 500 calls/day; app estimates $0.005/call for accounting.
- LLM: $0 by default (template briefs).

## Known limitations

- Website audit reads the fetched homepage only; quote/booking/chat detection is keyword-based and can miss JS-rendered widgets. Findings say “on fetched page.”
- Provider coverage/fields vary; Yelp records have no website/email in the search API, so audits for those leads record `not_found` (unknown), not a negative.
- Notifications are recorded and sent only when SMTP/Telegram are configured *and* enabled per campaign; otherwise they are logged `skipped_not_configured`.
- No automated outreach is implemented — by design. The system prepares leads/briefs for human outreach; calling/texting/emailing requires separate explicit configuration, authorization, and compliance work (prompt §17).
- Auth is single-admin Basic/token auth, appropriate for a single-operator tool; add OAuth/multi-user before team use.

## Acceptance criteria (prompt §19) — status

| # | Criterion | Status |
|---|---|---|
| 1 | Runs without user's computer on | ⏳ Requires your cloud account — code is a single always-on service + Dockerfile/render.yaml; not deployed here (no credentials) |
| 2 | Persistent scheduler triggers daily cycle | ✅ Locally (APScheduler + idempotent run keys); ⏳ verify in production after deploy |
| 3 | All six industries | ✅ Tested |
| 4 | Configurable geographic campaigns | ✅ Tested (campaign CRUD) |
| 5 | Discovery returns real records with valid credentials | ⏳ Requires your Google/Yelp API keys — adapters make real HTTP calls; verified only as “not configured” locally |
| 6 | Source info retained per lead | ✅ (data_sources table) |
| 7 | Missing data ≠ verified negative | ✅ Tested (audit `not_found` → features `None`) |
| 8 | Explainable score, separate confidence | ✅ Tested |
| 9 | Dedupe + updates without resetting pipeline | ✅ Tested |
| 10 | Pipeline changes/notes survive restarts | ✅ DB-backed (Postgres in prod); locally SQLite |
| 11 | Accurate daily report counts | ✅ Generated per run, shown in dashboard |
| 12 | API failures / rate limits / interruptions handled | ✅ Retries with backoff, 429 → ProviderError, partial/failed status — never silent success |
| 13 | Spending limits prevent unnecessary usage | ✅ Daily/monthly caps + per-day discovery limits, tested |
| 14 | CSV export works | ✅ Tested |
| 15 | No fabricated leads/claims | ✅ Tested (no-key run = failed, 0 leads; synthetic is test-only & labeled) |
| 16 | Auth & secret handling tested | ✅ Tested (401 on bad auth; settings never leak values) |
| 17 | Automated tests pass | ✅ See test run in delivery report |
| 18 | Deployment & recovery documented | ✅ This README; recovery = redeploy + Postgres backups/snapshots from your provider |

## What you must provide to go live

1. A cloud account (Render, Fly, or Railway) and deploy this repo.
2. Managed PostgreSQL (created by `render.yaml` on Render, or attached on Fly/Railway) → `DATABASE_URL`.
3. `GOOGLE_PLACES_API_KEY` and/or `YELP_API_KEY`.
4. A strong `ADMIN_PASSWORD` (and `SECRET_KEY`).
5. Optionally: SMTP/Telegram credentials for notifications, an LLM key if you want the polish hook.
Then run a small live pilot (one city, one industry, low daily caps) before enabling full daily discovery.
