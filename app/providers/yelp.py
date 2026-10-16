import httpx
from .base import BaseProvider, ProviderNotConfigured, ProviderError
from ..config import get_settings

class YelpProvider(BaseProvider):
    name = "yelp"
    cost_per_request_usd = 0.005
    def __init__(self, api_key=None):
        self.api_key = api_key if api_key is not None else get_settings().yelp_api_key
    def is_configured(self): return bool(self.api_key)
    def search(self, *, term, location, limit=20):
        if not self.is_configured():
            raise ProviderNotConfigured("yelp: YELP_API_KEY is not configured")
        try:
            r = httpx.get("https://api.yelp.com/v3/businesses/search",
                          params={"term": term, "location": location, "limit": min(limit, 50)},
                          headers={"Authorization": f"Bearer {self.api_key}"}, timeout=20)
        except httpx.HTTPError as e:
            raise ProviderError(f"yelp request failed: {e}")
        if r.status_code == 429:
            raise ProviderError("yelp rate limited (429)")
        if r.status_code >= 400:
            raise ProviderError(f"yelp HTTP {r.status_code}: {r.text[:200]}")
        out = []
        for b in r.json().get("businesses", []):
            loc = b.get("location") or {}
            out.append({
                "provider_id": b.get("id",""), "name": b.get("name",""),
                "address": " ".join([x for x in [loc.get("address1",""), loc.get("address2","")] if x]),
                "city": loc.get("city",""), "state": loc.get("state",""), "zip": loc.get("zip_code",""),
                "phone": b.get("display_phone","") or b.get("phone",""), "website": "", "email": "",
                "rating": b.get("rating"), "review_count": b.get("review_count"),
                "listing_url": b.get("url",""), "hours": {},
            })
        return out
