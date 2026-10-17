import csv, io, json, datetime
from urllib.parse import quote_plus
from fastapi import FastAPI, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
from .db import get_db, init_db, SessionLocal
from .config import get_settings
from .models import Campaign, Business, ResearchRun, DailyReport, PipelineEvent, ApiUsage, FollowUpTask
from .industries import INDUSTRIES, INDUSTRY_KEYS
from .california import CA_REGIONS, region_list, region_by_slug, campaign_name_for
from .auth import require_auth
from .runner import run_campaign, month_spend
from . import scheduler as sched

app = FastAPI(title="Cloud AI Lead Generation Agent")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

@app.on_event("startup")
def startup():
    init_db()
    # Seed example campaign (Pomona) if none exists — configurable, not hardcoded in logic
    db = SessionLocal()
    try:
        if not db.query(Campaign).first():
            db.add(Campaign(name="Pomona — All Industries (example)",
                            cities=json.dumps(["Pomona","Ontario","Rancho Cucamonga","Upland","Claremont"]),
                            states=json.dumps(["CA"]), industries=json.dumps(INDUSTRY_KEYS)))
            db.commit()
    finally: db.close()
    try: sched.start_scheduler()
    except Exception: pass  # scheduler failure must not hide health endpoint; runs also triggerable manually

@app.get("/health")
def health():
    return {"status": "ok", "env": get_settings().app_env}

# ---------- API: campaigns ----------
@app.get("/api/campaigns", dependencies=[Depends(require_auth)])
def list_campaigns(db: Session = Depends(get_db)):
    return [{"id": c.id, "name": c.name, "cities": c.j("cities",[]), "industries": c.j("industries",[]),
             "active": c.active, "paused": c.paused, "schedule_time": c.schedule_time, "timezone": c.timezone,
             "min_lead_score": c.min_lead_score, "daily_budget_usd": c.daily_budget_usd} for c in db.query(Campaign).all()]

@app.post("/api/campaigns", dependencies=[Depends(require_auth)])
def create_campaign(payload: dict, db: Session = Depends(get_db)):
    name = str(payload.get("name","")).strip()
    if not name: raise HTTPException(422, "name is required")
    industries = payload.get("industries", INDUSTRY_KEYS)
    bad = [i for i in industries if i not in INDUSTRIES]
    if bad: raise HTTPException(422, f"unknown industries: {bad}")
    c = Campaign(name=name, cities=json.dumps(payload.get("cities",[])), states=json.dumps(payload.get("states",["CA"])),
                 zip_codes=json.dumps(payload.get("zip_codes",[])), industries=json.dumps(industries),
                 max_discover_per_day=int(payload.get("max_discover_per_day",50)),
                 max_qualify_per_day=int(payload.get("max_qualify_per_day",25)),
                 min_rating=float(payload.get("min_rating",0)), min_review_count=int(payload.get("min_review_count",0)),
                 min_lead_score=int(payload.get("min_lead_score",60)),
                 daily_budget_usd=float(payload.get("daily_budget_usd",5.0)),
                 monthly_budget_usd=float(payload.get("monthly_budget_usd",100.0)),
                 schedule_time=str(payload.get("schedule_time","06:00")), timezone=str(payload.get("timezone","America/Los_Angeles")),
                 providers=json.dumps(payload.get("providers",["google_places","yelp"])))
    db.add(c); db.commit(); db.refresh(c)
    try: sched.sync_jobs()
    except Exception: pass
    return {"id": c.id, "name": c.name}

@app.patch("/api/campaigns/{cid}", dependencies=[Depends(require_auth)])
def update_campaign(cid: int, payload: dict, db: Session = Depends(get_db)):
    c = db.get(Campaign, cid)
    if not c: raise HTTPException(404, "campaign not found")
    for k in ["name","schedule_time","timezone"]:
        if k in payload: setattr(c, k, str(payload[k]))
    for k in ["max_discover_per_day","max_qualify_per_day","min_review_count","min_lead_score"]:
        if k in payload: setattr(c, k, int(payload[k]))
    for k in ["daily_budget_usd","monthly_budget_usd","min_rating"]:
        if k in payload: setattr(c, k, float(payload[k]))
    for k in ["cities","states","zip_codes","industries","providers"]:
        if k in payload: setattr(c, k, json.dumps(payload[k]))
    if "paused" in payload: c.paused = bool(payload["paused"])
    if "active" in payload: c.active = bool(payload["active"])
    db.commit()
    try: sched.sync_jobs()
    except Exception: pass
    return {"id": c.id, "paused": c.paused, "active": c.active}

@app.post("/api/campaigns/{cid}/pause", dependencies=[Depends(require_auth)])
def pause_campaign(cid: int, db: Session = Depends(get_db)):
    c = db.get(Campaign, cid)
    if not c: raise HTTPException(404, "campaign not found")
    c.paused = True; db.commit(); return {"id": cid, "paused": True}

@app.post("/api/campaigns/{cid}/resume", dependencies=[Depends(require_auth)])
def resume_campaign(cid: int, db: Session = Depends(get_db)):
    c = db.get(Campaign, cid)
    if not c: raise HTTPException(404, "campaign not found")
    c.paused = False; db.commit()
    try: sched.sync_jobs()
    except Exception: pass
    return {"id": cid, "paused": False}

@app.post("/api/campaigns/{cid}/run", dependencies=[Depends(require_auth)])
def trigger_run(cid: int, db: Session = Depends(get_db)):
    c = db.get(Campaign, cid)
    if not c: raise HTTPException(404, "campaign not found")
    run = run_campaign(db, c, trigger="manual")
    return {"run_id": run.id, "status": run.status, "discovered": run.discovered, "new_saved": run.new_saved,
            "duplicates": run.duplicates, "qualified": run.qualified, "error_summary": run.error_summary,
            "api_cost_usd": run.api_cost_usd}

# ---------- API: leads ----------
def _lead_dict(b):
    return {"id": b.id, "name": b.name, "industry": b.industry, "city": b.city, "state": b.state,
            "phone": b.phone, "email": b.email, "website": b.website, "rating": b.rating,
            "review_count": b.review_count, "lead_score": b.lead_score, "confidence": b.confidence,
            "score_tier": b.score_tier, "pipeline_stage": b.pipeline_stage, "sales_status": b.sales_status,
            "recommended_offer": b.recommended_offer, "opening_line": b.opening_line,
            "do_not_contact": b.do_not_contact, "is_test": b.is_test, "notes": b.notes}

@app.get("/api/leads", dependencies=[Depends(require_auth)])
def api_leads(q: str = "", industry: str = "", min_score: int = 0, stage: str = "", db: Session = Depends(get_db)):
    query = db.query(Business)
    if q: query = query.filter(Business.name.ilike(f"%{q}%"))
    if industry: query = query.filter_by(industry=industry)
    if stage: query = query.filter_by(pipeline_stage=stage)
    leads = [b for b in query.order_by(Business.lead_score.desc().nullslast()).all() if (b.lead_score or 0) >= min_score]
    return [_lead_dict(b) for b in leads]

@app.get("/api/leads/{bid}", dependencies=[Depends(require_auth)])
def api_lead(bid: int, db: Session = Depends(get_db)):
    b = db.get(Business, bid)
    if not b: raise HTTPException(404, "lead not found")
    d = _lead_dict(b); d["sales_brief"] = b.sales_brief; d["address"] = b.address
    d["evidence"] = [{"kind": e.kind, "strength": e.strength, "text": e.text} for e in b.evidence]
    d["sources"] = [{"provider": s.provider, "provider_id": s.provider_id, "source_url": s.source_url} for s in b.sources]
    return d

@app.post("/api/leads/{bid}/pipeline", dependencies=[Depends(require_auth)])
async def update_pipeline(bid: int, request: Request, db: Session = Depends(get_db)):
    b = db.get(Business, bid)
    if not b: raise HTTPException(404, "lead not found")
    form = await request.form() if "form" in request.headers.get("content-type","") else {}
    try: payload = await request.json()
    except Exception: payload = dict(form)
    new_status = payload.get("sales_status") or payload.get("to_status")
    note = payload.get("note","")
    if new_status:
        from .models import SALES_STATUSES
        if new_status not in SALES_STATUSES: raise HTTPException(422, f"invalid sales status {new_status}")
        old = b.sales_status; b.sales_status = new_status
        if new_status == "Do not contact": b.do_not_contact = True; b.pipeline_stage = "DO_NOT_CONTACT"
        db.add(PipelineEvent(business_id=b.id, from_status=old, to_status=new_status, kind="sales_status", note=note))
    if payload.get("notes") is not None: b.notes = str(payload["notes"])
    if note and not new_status:
        db.add(PipelineEvent(business_id=b.id, kind="note", note=note))
    db.commit()
    if "text/html" in request.headers.get("accept",""):
        return RedirectResponse(f"/leads/{bid}", status_code=303)
    return {"id": bid, "sales_status": b.sales_status, "do_not_contact": b.do_not_contact}

@app.get("/api/runs", dependencies=[Depends(require_auth)])
def api_runs(db: Session = Depends(get_db)):
    return [{"id": r.id, "campaign_id": r.campaign_id, "status": r.status, "trigger": r.trigger,
             "discovered": r.discovered, "new_saved": r.new_saved, "error_summary": r.error_summary,
             "api_cost_usd": r.api_cost_usd, "started_at": str(r.started_at)} for r in db.query(ResearchRun).order_by(ResearchRun.id.desc()).all()]

@app.get("/api/reports", dependencies=[Depends(require_auth)])
def api_reports(db: Session = Depends(get_db)):
    return [{"id": r.id, "run_id": r.run_id, "report": json.loads(r.report_json or "{}")} for r in db.query(DailyReport).order_by(DailyReport.id.desc()).all()]

@app.get("/api/settings", dependencies=[Depends(require_auth)])
def api_settings():
    s = get_settings()
    # Secrets NEVER returned — only configured/not-configured booleans
    return {"env": s.app_env, "database": "configured" if s.database_url else "missing",
            "google_places_api_key": "configured" if s.google_places_api_key else "not_configured",
            "yelp_api_key": "configured" if s.yelp_api_key else "not_configured",
            "llm": "configured" if s.openai_api_key else "not_configured (optional — templates work without it)",
            "admin_password": "configured" if s.admin_password else "not_configured",
            "notifications_email": "configured" if s.smtp_url else "not_configured",
            "telegram": "configured" if s.telegram_bot_token else "not_configured",
            "synthetic_provider": "enabled (test env only)" if s.synthetic_allowed else "disabled"}

@app.get("/export/leads.csv", dependencies=[Depends(require_auth)])
def export_csv(db: Session = Depends(get_db)):
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["id","name","industry","city","state","zip","phone","email","website","rating","review_count",
                "lead_score","confidence","tier","pipeline_stage","sales_status","recommended_offer","do_not_contact","is_test"])
    for b in db.query(Business).order_by(Business.lead_score.desc().nullslast()).all():
        w.writerow([b.id,b.name,b.industry,b.city,b.state,b.zip_code,b.phone,b.email,b.website,b.rating,b.review_count,
                    b.lead_score,b.confidence,b.score_tier,b.pipeline_stage,b.sales_status,b.recommended_offer,b.do_not_contact,b.is_test])
    return PlainTextResponse(out.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=leads.csv"})

# ---------- Dashboard (HTML) ----------
@app.get("/", response_class=HTMLResponse)
def overview(request: Request, db: Session = Depends(get_db)):
    require_auth(request)
    last_run = db.query(ResearchRun).order_by(ResearchRun.id.desc()).first()
    last_success = db.query(ResearchRun).filter_by(status="completed").order_by(ResearchRun.id.desc()).first()
    today = datetime.date.today()
    counts = {"new_today": sum(1 for b in db.query(Business).all() if b.created_at and b.created_at.date() == today),
              "qualified": db.query(Business).filter(Business.lead_score >= 60).count(),
              "high": db.query(Business).filter(Business.lead_score >= 80).count(),
              "ready": db.query(Business).filter_by(pipeline_stage="READY_FOR_OUTREACH").count(),
              "followups": db.query(FollowUpTask).filter_by(done=False).count(),
              "month_cost": month_spend(db)}
    try: nxt = sched.next_run_time()
    except Exception: nxt = None
    return templates.TemplateResponse(request, "overview.html", {"last_run": last_run,
                                        "last_success": last_success, "next_run": nxt, "counts": counts})

@app.get("/leads", response_class=HTMLResponse)
def leads_page(request: Request, q: str = "", industry: str = "", min_score: int = 0, db: Session = Depends(get_db)):
    require_auth(request)
    query = db.query(Business)
    if q: query = query.filter(Business.name.ilike(f"%{q}%"))
    if industry: query = query.filter_by(industry=industry)
    leads = [b for b in query.order_by(Business.lead_score.desc().nullslast()).all() if (b.lead_score or 0) >= min_score]
    return templates.TemplateResponse(request, "leads.html", {"leads": leads, "q": q,
                                      "industry": industry, "min_score": min_score, "industries": INDUSTRY_KEYS})

@app.get("/leads/{bid}", response_class=HTMLResponse)
def lead_detail(request: Request, bid: int, db: Session = Depends(get_db)):
    require_auth(request)
    b = db.get(Business, bid)
    if not b: raise HTTPException(404, "lead not found")
    breakdown = ""
    if b.scores: breakdown = json.dumps(json.loads(b.scores[-1].breakdown_json or "{}"), indent=2)
    return templates.TemplateResponse(request, "lead_detail.html", {"b": b, "breakdown": breakdown})

@app.get("/campaigns", response_class=HTMLResponse)
def campaigns_page(request: Request, error: str = "", msg: str = "", db: Session = Depends(get_db)):
    require_auth(request)
    rows = db.query(Campaign).all()
    campaigns = [{"id": c.id, "name": c.name,
                  "cities_text": ", ".join(c.j("cities", [])),
                  "states_text": ", ".join(c.j("states", ["CA"])),
                  "industries": c.j("industries", []),
                  "schedule_time": c.schedule_time, "timezone": c.timezone,
                  "paused": c.paused, "active": c.active,
                  "max_discover_per_day": c.max_discover_per_day,
                  "max_qualify_per_day": c.max_qualify_per_day,
                  "min_lead_score": c.min_lead_score,
                  "daily_budget_usd": c.daily_budget_usd, "monthly_budget_usd": c.monthly_budget_usd}
                 for c in rows]
    existing_names = {c.name for c in rows}
    ca_regions = [{**r, "campaign_name": campaign_name_for(r["name"]),
                   "exists": campaign_name_for(r["name"]) in existing_names}
                  for r in region_list()]
    return templates.TemplateResponse(request, "campaigns.html",
                                        {"campaigns": campaigns, "industries": INDUSTRY_KEYS,
                                         "industry_labels": {k: v["label"] for k, v in INDUSTRIES.items()},
                                         "ca_regions": ca_regions,
                                         "error": error, "msg": msg})

# ---------- Dashboard campaign controls (HTML forms; the /api routes need a JSON client) ----------
@app.post("/campaigns/{cid}/pause")
def campaigns_pause(cid: int, request: Request, db: Session = Depends(get_db)):
    require_auth(request)
    c = db.get(Campaign, cid)
    if not c: raise HTTPException(404, "campaign not found")
    c.paused = True; db.commit()
    try: sched.sync_jobs()
    except Exception: pass
    return RedirectResponse("/campaigns", status_code=303)

@app.post("/campaigns/{cid}/resume")
def campaigns_resume(cid: int, request: Request, db: Session = Depends(get_db)):
    require_auth(request)
    c = db.get(Campaign, cid)
    if not c: raise HTTPException(404, "campaign not found")
    c.paused = False; db.commit()
    try: sched.sync_jobs()
    except Exception: pass
    return RedirectResponse("/campaigns", status_code=303)

@app.post("/campaigns/{cid}/run")
def campaigns_run(cid: int, request: Request, db: Session = Depends(get_db)):
    require_auth(request)
    c = db.get(Campaign, cid)
    if not c: raise HTTPException(404, "campaign not found")
    run_campaign(db, c, trigger="manual")
    return RedirectResponse("/jobs", status_code=303)

@app.post("/campaigns-pilot")
def campaigns_create_pilot(request: Request, city: str = Form("Pomona"),
                           industry: str = Form("roofing"), db: Session = Depends(get_db)):
    require_auth(request)
    city = city.strip() or "Pomona"
    if industry not in INDUSTRIES: raise HTTPException(422, f"unknown industry: {industry}")
    c = Campaign(name=f"Pilot — {city} — {industry}", cities=json.dumps([city]),
                 states=json.dumps(["CA"]), industries=json.dumps([industry]),
                 max_discover_per_day=10, max_qualify_per_day=10,
                 daily_budget_usd=1.0, monthly_budget_usd=100.0,
                 providers=json.dumps(["google_places", "yelp"]))
    db.add(c); db.commit()
    try: sched.sync_jobs()
    except Exception: pass
    return RedirectResponse("/campaigns", status_code=303)

# ---------- Dashboard campaign create/edit (HTML forms) ----------
def _split_list(raw):
    """Split a textarea value on commas and/or newlines into a clean list."""
    out = []
    for part in (raw or "").replace("\n", ",").split(","):
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return out


def _parse_campaign_form(form):
    """Validate dashboard form data the same way the JSON API does.

    Returns (values_dict, error_message). error_message is '' on success —
    callers show it on the page instead of failing with a 500."""
    name = str(form.get("name", "")).strip()
    if not name:
        return None, "Campaign name is required."
    industries = [str(i) for i in form.getlist("industries")]
    bad = [i for i in industries if i not in INDUSTRIES]
    if bad:
        return None, f"Unknown industries: {', '.join(bad)}"
    if not industries:
        return None, "Select at least one industry."
    try:
        values = {
            "name": name,
            "cities": _split_list(form.get("cities", "")),
            "states": _split_list(form.get("states", "")) or ["CA"],
            "industries": industries,
            "max_discover_per_day": int(form.get("max_discover_per_day") or 50),
            "max_qualify_per_day": int(form.get("max_qualify_per_day") or 25),
            "min_lead_score": int(form.get("min_lead_score") or 60),
            "daily_budget_usd": float(form.get("daily_budget_usd") or 5.0),
            "monthly_budget_usd": float(form.get("monthly_budget_usd") or 100.0),
            "schedule_time": str(form.get("schedule_time") or "06:00").strip(),
            "timezone": str(form.get("timezone") or "America/Los_Angeles").strip(),
        }
    except (TypeError, ValueError):
        return None, "Limits, budgets and minimum score must be numbers."
    return values, ""


def _apply_campaign_form(c, values):
    c.name = values["name"]
    c.cities = json.dumps(values["cities"])
    c.states = json.dumps(values["states"])
    c.industries = json.dumps(values["industries"])
    c.max_discover_per_day = values["max_discover_per_day"]
    c.max_qualify_per_day = values["max_qualify_per_day"]
    c.min_lead_score = values["min_lead_score"]
    c.daily_budget_usd = values["daily_budget_usd"]
    c.monthly_budget_usd = values["monthly_budget_usd"]
    c.schedule_time = values["schedule_time"]
    c.timezone = values["timezone"]
    return c


@app.post("/campaigns")
async def campaigns_create_form(request: Request, db: Session = Depends(get_db)):
    require_auth(request)
    values, error = _parse_campaign_form(await request.form())
    if error:
        return RedirectResponse(f"/campaigns?error={quote_plus(error)}", status_code=303)
    c = _apply_campaign_form(Campaign(providers=json.dumps(["google_places"])), values)
    db.add(c); db.commit()
    try: sched.sync_jobs()
    except Exception: pass
    return RedirectResponse(f"/campaigns?msg={quote_plus('Campaign created: ' + c.name)}", status_code=303)


@app.post("/campaigns/{cid}/edit")
async def campaigns_edit_form(cid: int, request: Request, db: Session = Depends(get_db)):
    require_auth(request)
    c = db.get(Campaign, cid)
    if not c: raise HTTPException(404, "campaign not found")
    values, error = _parse_campaign_form(await request.form())
    if error:
        return RedirectResponse(f"/campaigns?error={quote_plus(error)}", status_code=303)
    _apply_campaign_form(c, values)
    db.commit()
    try: sched.sync_jobs()
    except Exception: pass
    return RedirectResponse(f"/campaigns?msg={quote_plus('Campaign updated: ' + c.name)}", status_code=303)


@app.post("/campaigns-ca/{slug}")
def campaigns_create_ca_region(slug: str, request: Request, db: Session = Depends(get_db)):
    require_auth(request)
    region = region_by_slug(slug)
    if not region: raise HTTPException(404, "unknown California region")
    name = campaign_name_for(region["name"])
    if db.query(Campaign).filter_by(name=name).first():
        return RedirectResponse(
            f"/campaigns?msg={quote_plus(name + ' already exists — not duplicated')}",
            status_code=303)
    c = Campaign(name=name, cities=json.dumps(region["cities"]),
                 states=json.dumps(["CA"]), industries=json.dumps(INDUSTRY_KEYS),
                 schedule_time=region["schedule_time"],
                 providers=json.dumps(["google_places"]))
    db.add(c); db.commit()
    try: sched.sync_jobs()
    except Exception: pass
    return RedirectResponse(f"/campaigns?msg={quote_plus('Campaign created: ' + name)}", status_code=303)


@app.get("/pipeline", response_class=HTMLResponse)
def pipeline_page(request: Request, db: Session = Depends(get_db)):
    require_auth(request)
    from .models import SALES_STATUSES
    lines = []
    for st in SALES_STATUSES:
        items = db.query(Business).filter_by(sales_status=st).all()
        lines.append(f"## {st} ({len(items)})\n" + "\n".join(f"- {b.name} ({b.industry}, {b.city}) score={b.lead_score}" for b in items))
    return templates.TemplateResponse(request, "simple.html", {"title": "Pipeline", "body": "\n\n".join(lines)})

@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, db: Session = Depends(get_db)):
    require_auth(request)
    body = "\n".join(f"Run #{r.id} campaign={r.campaign_id} {r.trigger} status={r.status} discovered={r.discovered} new={r.new_saved} dup={r.duplicates} qualified={r.qualified} cost=${r.api_cost_usd} errors={r.error_summary}"
                     for r in db.query(ResearchRun).order_by(ResearchRun.id.desc()).all()) or "No jobs yet."
    return templates.TemplateResponse(request, "simple.html", {"title": "Jobs", "body": body})

@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request, db: Session = Depends(get_db)):
    require_auth(request)
    body = "\n\n".join(f"Report #{r.id} (run {r.run_id}):\n{json.dumps(json.loads(r.report_json or '{}'), indent=2)}"
                       for r in db.query(DailyReport).order_by(DailyReport.id.desc()).all()) or "No reports yet."
    return templates.TemplateResponse(request, "simple.html", {"title": "Daily Reports", "body": body})

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    require_auth(request)
    return templates.TemplateResponse(request, "simple.html", {"title": "Settings (secrets never shown)",
                                      "body": json.dumps(api_settings(), indent=2)})
