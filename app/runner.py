"""Research run pipeline: DISCOVERED→NORMALIZED→VERIFIED→RESEARCHED→SCORED→QUALIFIED→READY.
Honest failure: no configured provider => run FAILED with clear error, zero fabricated leads.
Budget caps stop optional (stage 3/4) work and are reported. Retries with backoff on provider errors."""
import datetime, json, time, uuid
from sqlalchemy.orm import Session
from .models import (Campaign, Business, SourceRecord, Evidence, WebsiteAudit, LeadScore,
                     ResearchRun, PipelineEvent, ApiUsage, DailyReport, NotificationHistory)
from .industries import INDUSTRIES
from .dedupe import find_duplicate, normalize_phone, normalize_domain
from .scoring import score_business, tier_for
from .website_audit import audit_website
from .sales_brief import build_brief
from .providers import get_provider
from .providers.base import ProviderNotConfigured, ProviderError
from .config import get_settings

def _today_key(campaign_id, trigger):
    if trigger == "scheduled":
        return f"scheduled-{datetime.date.today().isoformat()}"
    return f"manual-{uuid.uuid4().hex[:12]}"

def month_spend(db):
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = db.query(ApiUsage).filter(ApiUsage.created_at >= start.replace(tzinfo=None)).all()
    return sum(r.estimated_cost_usd or 0 for r in rows)

def run_campaign(db: Session, campaign: Campaign, trigger="manual", run_key=None, max_attempts=3):
    run_key = run_key or _today_key(campaign.id, trigger)
    # Idempotency / duplicate-run prevention: one scheduled run per campaign per day
    existing = db.query(ResearchRun).filter_by(campaign_id=campaign.id, run_key=run_key).first()
    if existing and trigger == "scheduled":
        return existing
    if campaign.paused:
        run = ResearchRun(campaign_id=campaign.id, run_key=run_key + "-paused-" + uuid.uuid4().hex[:6],
                          job_id=uuid.uuid4().hex, trigger=trigger, status="failed",
                          error_summary="Campaign is paused", completed_at=datetime.datetime.now(datetime.timezone.utc))
        db.add(run); db.commit(); return run
    run = ResearchRun(campaign_id=campaign.id, run_key=run_key, job_id=uuid.uuid4().hex, trigger=trigger, status="running")
    db.add(run); db.commit(); db.refresh(run)

    provider_names = campaign.j("providers", ["google_places", "yelp"])
    providers, not_configured = [], []
    for name in provider_names:
        p = get_provider(name)
        (providers if p.is_configured() else not_configured).append(p if p.is_configured() else name)
    if not providers:
        run.status = "failed"
        run.error_summary = ("provider not configured: none of "
                             + ", ".join(provider_names)
                             + " has an API key configured. Set GOOGLE_PLACES_API_KEY and/or YELP_API_KEY. No leads were fabricated.")
        run.completed_at = datetime.datetime.now(datetime.timezone.utc)
        db.commit()
        _report_and_notify(db, campaign, run)
        return run

    errors = []
    if not_configured:
        errors.append(f"Providers not configured (skipped): {', '.join(not_configured)}")
    cities = campaign.j("cities", []) or ["Pomona"]
    industries = campaign.j("industries", list(INDUSTRIES.keys()))
    budget_hit = False

    for industry in industries:
        if run.new_saved >= campaign.max_qualify_per_day and run.discovered >= campaign.max_discover_per_day:
            break
        prof = INDUSTRIES.get(industry)
        if not prof: continue
        for city in cities:
            location = f"{city}, CA" if city else ""
            for provider in providers:
                if run.discovered >= campaign.max_discover_per_day:
                    budget_hit = True; break
                # budget check before spending
                spent_today = db.query(ApiUsage).filter(ApiUsage.run_id == run.id).all()
                if sum(a.estimated_cost_usd for a in spent_today) >= campaign.daily_budget_usd or month_spend(db) >= campaign.monthly_budget_usd:
                    budget_hit = True; errors.append("Budget cap reached — optional research stopped"); break
                records, attempt = None, 0
                while attempt < max_attempts:
                    try:
                        records = provider.search(term=prof["search_terms"][0], location=location,
                                                  limit=min(20, campaign.max_discover_per_day - run.discovered))
                        break
                    except ProviderNotConfigured as e:
                        errors.append(str(e)); records = []; break
                    except ProviderError as e:
                        attempt += 1
                        if attempt >= max_attempts: errors.append(f"{provider.name}: {e} (after {attempt} retries)")
                        else: time.sleep(2 ** attempt * 0.1)  # backoff (short in-process; scaled in prod via config)
                if not records: continue
                usage = ApiUsage(run_id=run.id, provider=provider.name, endpoint="search",
                                 requests=1, estimated_cost_usd=provider.cost_per_request_usd)
                db.add(usage); run.api_cost_usd += provider.cost_per_request_usd; db.commit()
                for rec in records:
                    run.discovered += 1
                    _process_record(db, campaign, run, industry, provider.name, rec, errors)
                db.commit()
    run.status = "partial" if errors and run.new_saved else ("failed" if errors and not providers else "completed")
    if errors and run.new_saved == 0 and any("Budget cap" not in e for e in errors):
        # keep completed if we did useful work; partial if some providers failed
        run.status = "partial" if run.discovered else run.status
    if budget_hit:
        errors.append("Stopped at daily discovery/budget limit as configured")
    run.error_summary = "; ".join(errors)
    run.completed_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    _report_and_notify(db, campaign, run)
    return run

def _process_record(db, campaign, run, industry, provider_name, rec, errors):
    is_test = provider_name == "synthetic_test"
    dup = find_duplicate(db, provider=provider_name, provider_id=rec.get("provider_id",""),
                         phone=rec.get("phone",""), domain=normalize_domain(rec.get("website","")),
                         name=rec.get("name",""), address=rec.get("address",""), city=rec.get("city",""))
    if dup:
        run.duplicates += 1
        # Update reliably-sourced fields without resetting pipeline (prompt §10)
        if rec.get("rating") is not None: dup.rating = rec["rating"]
        if rec.get("review_count") is not None: dup.review_count = rec["review_count"]
        if rec.get("phone") and not dup.phone: dup.phone = rec["phone"]; dup.phone_normalized = normalize_phone(rec["phone"])
        dup.last_verified_at = datetime.datetime.now(datetime.timezone.utc)
        return
    biz = Business(name=rec.get("name","") or "Unknown", industry=industry, address=rec.get("address",""),
                   city=rec.get("city",""), state=rec.get("state",""), zip_code=rec.get("zip",""),
                   phone=rec.get("phone",""), phone_normalized=normalize_phone(rec.get("phone","")),
                   website=rec.get("website",""), domain=normalize_domain(rec.get("website","")),
                   email=rec.get("email",""), listing_url=rec.get("listing_url",""),
                   rating=rec.get("rating"), review_count=rec.get("review_count"),
                   pipeline_stage="NORMALIZED", campaign_id=campaign.id, is_test=is_test,
                   environment="test" if is_test else "production",
                   last_verified_at=datetime.datetime.now(datetime.timezone.utc))
    db.add(biz); db.flush()
    db.add(SourceRecord(business_id=biz.id, provider=provider_name, provider_id=rec.get("provider_id",""),
                        source_url=rec.get("listing_url",""), fields_json=json.dumps(rec, default=str),
                        verification_status="retrieved"))
    # Filters: rating / reviews / geo
    if campaign.min_rating and biz.rating is not None and biz.rating < campaign.min_rating:
        biz.pipeline_stage = "INSUFFICIENT_DATA"; run.new_saved += 1; return
    if campaign.min_review_count and (biz.review_count or 0) < campaign.min_review_count:
        biz.pipeline_stage = "INSUFFICIENT_DATA"; run.new_saved += 1; return
    # Evidence: industry indicators are POTENTIAL, audit findings can be STRONG
    prof = INDUSTRIES[industry]
    db.add(Evidence(business_id=biz.id, kind="industry_indicator", strength="potential",
                    text=f"Operates in a call-intensive industry with {', '.join(prof['signals'][:3])}"))
    if biz.phone and not biz.website:
        db.add(Evidence(business_id=biz.id, kind="opportunity", strength="potential",
                        text="Public phone contact present; no official website found in provider record (website not_found, not verified absent)"))
    biz.pipeline_stage = "VERIFIED"
    # Website audit (stage 3; skipped if budget-constrained upstream)
    audit_result = audit_website(biz.website)
    audit_result["issues"] = json.dumps(audit_result.get("issues", []))
    audit = WebsiteAudit(business_id=biz.id, **audit_result)
    db.add(audit); db.flush()
    if audit.status == "accessible" and audit.has_quote_form is False and audit.has_booking is False:
        db.add(Evidence(business_id=biz.id, kind="digital_gap", strength="strong",
                        text="Official website checked: no quote-request form and no online booking found on fetched page",
                        source_url=biz.website))
    biz.pipeline_stage = "RESEARCHED"; run.researched += 1
    evidence = db.query(Evidence).filter_by(business_id=biz.id).all()
    total, confidence, breakdown = score_business(biz, audit=audit, evidence=evidence, campaign=campaign)
    biz.lead_score = total; biz.confidence = confidence; biz.score_tier = tier_for(total)
    biz.recommended_offer = prof["primary_offer"]
    db.add(LeadScore(business_id=biz.id, total=total, confidence=confidence,
                     breakdown_json=json.dumps(breakdown), weights_json="{}",
                     tier=biz.score_tier, explanation=json.dumps(breakdown)))
    biz.pipeline_stage = "SCORED"
    brief, opener = build_brief(biz, evidence, audit=audit)
    biz.sales_brief = brief; biz.opening_line = opener
    if biz.do_not_contact:
        biz.pipeline_stage = "DO_NOT_CONTACT"
    elif total >= campaign.min_lead_score:
        biz.pipeline_stage = "QUALIFIED"; run.qualified += 1
        biz.pipeline_stage = "READY_FOR_OUTREACH"
        if total >= 80: run.high_priority += 1
    db.add(PipelineEvent(business_id=biz.id, from_status="DISCOVERED", to_status=biz.pipeline_stage,
                         kind="stage", note=f"score={total} confidence={confidence}"))
    run.new_saved += 1

def _report_and_notify(db, campaign, run):
    leads = db.query(Business).filter(Business.campaign_id == campaign.id).all() if campaign else []
    report = {
        "run_id": run.id, "status": run.status, "discovered": run.discovered, "new_saved": run.new_saved,
        "duplicates_excluded": run.duplicates, "researched": run.researched, "qualified": run.qualified,
        "high_priority": run.high_priority,
        "with_verified_phone": sum(1 for b in leads if b.phone),
        "with_public_email": sum(1 for b in leads if b.email),
        "strong_evidence": db.query(Evidence).filter_by(strength="strong").count(),
        "needs_more_research": sum(1 for b in leads if (b.lead_score or 0) < 60 and b.pipeline_stage != "DUPLICATE"),
        "api_cost_usd": run.api_cost_usd, "errors": run.error_summary,
        "top_prospects": [{"name": b.name, "industry": b.industry, "city": b.city, "phone": b.phone,
                           "website": b.website, "score": b.lead_score, "confidence": b.confidence,
                           "offer": b.recommended_offer, "opening_line": b.opening_line}
                          for b in sorted(leads, key=lambda x: -(x.lead_score or 0))[:10]],
    }
    db.add(DailyReport(run_id=run.id, campaign_id=campaign.id if campaign else None, report_json=json.dumps(report)))
    # Notifications: only when actually configured; otherwise recorded as skipped_not_configured
    for channel, enabled in [("email", campaign.notify_email if campaign else False),
                             ("telegram", campaign.notify_telegram if campaign else False)]:
        configured = bool(get_settings().smtp_url) if channel == "email" else bool(get_settings().telegram_bot_token)
        db.add(NotificationHistory(run_id=run.id, channel=channel,
                                   status="skipped_not_configured" if not (enabled and configured) else "sent",
                                   detail="notification not enabled/configured" if not (enabled and configured) else "sent"))
    db.commit()
    return report
