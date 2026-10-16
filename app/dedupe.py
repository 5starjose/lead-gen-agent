import re
from urllib.parse import urlparse
from sqlalchemy.orm import Session
from .models import Business, SourceRecord

def normalize_phone(p):
    if not p: return ""
    d = re.sub(r"\D", "", str(p))
    if len(d) == 11 and d.startswith("1"): d = d[1:]
    return d if len(d) == 10 else d

def normalize_domain(website):
    if not website: return ""
    u = website if "://" in website else "https://" + website
    try:
        host = (urlparse(u).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except Exception: return ""

def normalize_name(name):
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()

def find_duplicate(db: Session, *, provider=None, provider_id="", phone="", domain="", name="", address="", city=""):
    """Returns existing Business or None. Distinct locations of the same chain are NOT merged:
    name+domain/phone matches still require same address/city when both sides have an address."""
    if provider and provider_id:
        src = db.query(SourceRecord).filter_by(provider=provider, provider_id=provider_id).first()
        if src: return db.get(Business, src.business_id)
    phone_n = normalize_phone(phone)
    candidates = []
    if phone_n:
        candidates += db.query(Business).filter_by(phone_normalized=phone_n).all()
    if domain:
        candidates += db.query(Business).filter_by(domain=domain).all()
    if name and address:
        nn = normalize_name(name)
        for b in db.query(Business).filter_by(address=address).all():
            if normalize_name(b.name) == nn: return b
    # Among phone/domain candidates, require location compatibility (don't merge distinct locations)
    for b in candidates:
        if address and b.address and address.lower() != b.address.lower():
            continue  # different location — keep separate
        if city and b.city and city.lower() != b.city.lower() and address and b.address:
            continue
        return b
    return None
