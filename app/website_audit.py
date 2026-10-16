import httpx

KEYWORDS = {
    "has_contact": ["contact", "call us", "phone"],
    "has_quote_form": ["get a quote", "request a quote", "free estimate", "get an estimate", "request service"],
    "has_booking": ["book online", "schedule online", "book now", "schedule service", "online booking"],
    "has_chat": ["live chat", "chat with us", "chat widget", "drift", "intercom", "tawk"],
    "has_service_info": ["services", "our services"],
}

def audit_website(url):
    """Fetch the business's OWN official website only. Distinguishes:
    not_found (no website on record) vs not_checked vs accessible vs inaccessible.
    Feature False means checked-and-not-found on the fetched page; None means unknown."""
    result = {"url": url or "", "status": "not_found", "https": None, "has_contact": None,
              "has_quote_form": None, "has_booking": None, "has_chat": None,
              "has_service_info": None, "mobile_hint": "unknown", "issues": []}
    if not url:
        result["issues"] = ["no website on record (not_found, not a verified negative about the business)"]
        return result
    result["https"] = url.lower().startswith("https://")
    if not result["https"]:
        result["issues"].append("website is not HTTPS")
    try:
        r = httpx.get(url, timeout=10, follow_redirects=True,
                      headers={"User-Agent": "LeadGenAudit/1.0 (business website check)"})
    except Exception as e:
        result["status"] = "inaccessible"; result["issues"].append(f"fetch failed: {type(e).__name__}")
        return result
    if r.status_code >= 400:
        result["status"] = "inaccessible"; result["issues"].append(f"HTTP {r.status_code}")
        return result
    result["status"] = "accessible"
    text = r.text.lower()
    for field, words in KEYWORDS.items():
        result[field] = any(w in text for w in words)
    result["mobile_hint"] = "viewport-meta" if "viewport" in text else "no-viewport-meta"
    if result["mobile_hint"] == "no-viewport-meta":
        result["issues"].append("no viewport meta tag (possible mobile usability issue)")
    return result
