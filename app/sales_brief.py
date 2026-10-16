"""Deterministic template-based sales briefs (prompt §12). No LLM required.
Optional LLM hook: if an LLM key is configured, `llm_polish` interface exists but the
default path never calls it and never invents facts — it only rephrases supplied text."""
from .industries import INDUSTRIES
from .config import get_settings

DISCOVERY_QS = [
    "How are incoming calls handled when the team is out on jobs?",
    "What happens to a call that comes in after hours or while everyone is busy?",
    "Can customers book or request an estimate online today, or does that all go through the phone?",
    "How do you follow up on estimate requests that don't convert right away?",
    "Would faster response times to new inquiries be valuable to you?",
]

def build_brief(biz, evidence, audit=None):
    prof = INDUSTRIES.get(biz.industry, {})
    offer = biz.recommended_offer or prof.get("primary_offer", "AI receptionist")
    ev_lines = [e.text for e in (evidence or [])]
    summary = (f"{biz.name} is a {prof.get('label', biz.industry)} business"
               + (f" in {biz.city}" if biz.city else "")
               + ". Observed evidence: " + ("; ".join(ev_lines) if ev_lines else "limited public evidence — opportunity is unconfirmed.")
               )
    if prof.get("safety_note"):
        summary += f" Note: {prof['safety_note']}"
    # Opening line personalized ONLY with verified details (name + city from provider record)
    opener = ("Hi, I'm reaching out because I work with local service businesses on handling customer "
              "inquiries and booking requests more efficiently. Can I ask how you're currently handling "
              "calls when your team is busy out on jobs?")
    if biz.city:
        opener = (f"Hi, I'm reaching out because I work with {biz.city}-area service businesses on handling "
                  "customer inquiries and booking requests more efficiently. Can I ask how you're currently "
                  "handling calls when your team is busy out on jobs?")
    angle = ("Potential benefit: capturing and responding to inquiries that arrive while the team is working, "
             "without adding front-desk headcount. No results are guaranteed — this needs confirmation on a call.")
    if audit and audit.status == "accessible" and audit.has_booking is False:
        next_action = "Call the business"
    elif not biz.phone:
        next_action = "Verify the contact information"
    elif audit is None or audit.status in ("not_checked", "not_found"):
        next_action = "Review the website manually"
    else:
        next_action = "Call the business"
    brief = (f"## Opportunity summary\n{summary}\n\n## Recommended offer\n{offer}\n\n"
             f"## Suggested opening line\n{opener}\n\n## Discovery questions\n"
             + "\n".join(f"{i+1}. {q}" for i, q in enumerate(DISCOVERY_QS))
             + f"\n\n## Sales angle\n{angle}\n\n## Next action\n{next_action}\n")
    return brief, opener

def llm_polish(text):  # optional hook, NOT required and not called by default
    s = get_settings()
    if not (s.openai_api_key and s.llm_provider):
        return text
    return text  # interface stub: a configured deployment may rephrase here; facts must not change
