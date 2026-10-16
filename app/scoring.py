import json
from .industries import INDUSTRIES

DEFAULT_WEIGHTS = {  # prompt §9 — exact weights, configurable
    "industry_fit": 20, "opportunity_evidence": 25, "reputation": 15,
    "contact_quality": 15, "geographic_fit": 10, "sales_accessibility": 10, "digital_gaps": 5,
}

def tier_for(score):
    if score >= 80: return "High-priority prospect"
    if score >= 60: return "Qualified prospect"
    if score >= 40: return "Research further"
    return "Low priority"

def score_business(biz, audit=None, evidence=None, campaign=None, weights=None):
    """Explainable deterministic scoring. Returns (total, confidence, breakdown dict).
    Missing data lowers confidence; it never invents data."""
    w = dict(DEFAULT_WEIGHTS); 
    if weights: w.update(weights)
    evidence = evidence or []
    breakdown = {}
    # Industry fit (max w)
    prof = INDUSTRIES.get(biz.industry)
    ind = 0
    if prof:
        ind = 12  # in a target industry with phone/estimate workflows
        if prof.get("call_intensive"): ind += 4
        if prof.get("estimates") or prof.get("appointments"): ind += 4
        ind = min(ind, w["industry_fit"])
    breakdown["industry_fit"] = {"points": ind, "max": w["industry_fit"],
        "why": "Target industry with phone/estimate/scheduling workflows" if prof else "Not a target industry"}
    # Opportunity evidence — observed evidence outweighs generic indicators
    strong = sum(1 for e in evidence if getattr(e, "strength", "") == "strong")
    potential = sum(1 for e in evidence if getattr(e, "strength", "") == "potential")
    opp = min(w["opportunity_evidence"], strong * 9 + potential * 4)
    breakdown["opportunity_evidence"] = {"points": opp, "max": w["opportunity_evidence"],
        "why": f"{strong} strong, {potential} potential evidence item(s)"}
    # Reputation — rating+volume together; few reviews != bad prospect
    rep = 0
    if biz.rating is not None:
        rep += 5 if biz.rating >= 4.0 else 3 if biz.rating >= 3.0 else 1
    if biz.review_count is not None:
        rep += 10 if biz.review_count >= 100 else 7 if biz.review_count >= 25 else 4 if biz.review_count >= 5 else 2
    rep = min(rep, w["reputation"])
    breakdown["reputation"] = {"points": rep, "max": w["reputation"],
        "why": f"rating={biz.rating}, reviews={biz.review_count}"}
    # Contact quality
    cq = 0
    if biz.phone: cq += 8
    if biz.email: cq += 4
    if biz.website: cq += 3
    cq = min(cq, w["contact_quality"])
    breakdown["contact_quality"] = {"points": cq, "max": w["contact_quality"],
        "why": "phone/email/website presence as recorded (verified fields only)"}
    # Geographic fit
    geo = 0
    if campaign and biz.city:
        cities = campaign.j("cities", [])
        geo = w["geographic_fit"] if (not cities or biz.city in cities) else 4
    elif biz.city: geo = 6
    breakdown["geographic_fit"] = {"points": geo, "max": w["geographic_fit"], "why": f"city={biz.city or 'unknown'}"}
    # Sales accessibility / public presence
    acc = 0
    if biz.listing_url: acc += 4
    if biz.website: acc += 3
    if biz.phone: acc += 3
    acc = min(acc, w["sales_accessibility"])
    breakdown["sales_accessibility"] = {"points": acc, "max": w["sales_accessibility"], "why": "public listing/website/phone"}
    # Digital gaps — only when audit actually checked
    gaps = 0
    if audit and audit.status == "accessible":
        missing = sum(1 for v in [audit.has_quote_form, audit.has_booking, audit.has_chat] if v is False)
        gaps = min(w["digital_gaps"], missing * 2)
    breakdown["digital_gaps"] = {"points": gaps, "max": w["digital_gaps"],
        "why": "verified missing quote/booking/chat features" if audit and audit.status=="accessible" else "website not audited — no gap assumed"}
    total = sum(v["points"] for v in breakdown.values())
    total = max(0, min(100, round(total * 100 / sum(w.values())) if sum(w.values()) != 100 else total))
    # Confidence: completeness of verified data, kept separate from score
    checks = [bool(biz.phone), bool(biz.website), biz.rating is not None, bool(biz.address or biz.city),
              bool(evidence), bool(audit and audit.status == "accessible")]
    confidence = round(sum(checks) / len(checks), 2)
    return total, confidence, breakdown
