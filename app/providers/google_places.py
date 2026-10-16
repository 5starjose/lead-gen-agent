import httpx
from .base import BaseProvider, ProviderNotConfigured, ProviderError
from ..config import get_settings

class GooglePlacesProvider(BaseProvider):
    name = "google_places"
    cost_per_request_usd = 0.032  # Text Search (approx, configurable estimate)
    def __init__(self, api_key=None):
        self.api_key = api_key if api_key is not None else get_settings().google_places_api_key
    def is_configured(self): return bool(self.api_key)
    def search(self, *, term, location, limit=20):
        if not self.is_configured():
            raise ProviderNotConfigured("google_places: GOOGLE_PLACES_API_KEY is not configured")
        headers = {"X-Goog-Api-Key": self.api_key,
                   "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber,places.websiteUri,places.rating,places.userRatingCount,places.googleMapsUri,places.location"}
        body = {"textQuery": f"{term} in {location}", "maxResultCount": min(limit, 20)}
        try:
            r = httpx.post("https://places.googleapis.com/v1/places:searchText", json=body, headers=headers, timeout=20)
        except httpx.HTTPError as e:
            raise ProviderError(f"google_places request failed: {e}")
        if r.status_code == 429:
            raise ProviderError("google_places rate limited (429)")
        if r.status_code >= 400:
            raise ProviderError(f"google_places HTTP {r.status_code}: {r.text[:200]}")
        out = []
        for p in r.json().get("places", []):
            addr = p.get("formattedAddress", "")
            parts = [x.strip() for x in addr.split(",")]
            city = parts[-3] if len(parts) >= 3 else ""
            state_zip = parts[-2] if len(parts) >= 2 else ""
            sz = state_zip.split()
            out.append({
                "provider_id": p.get("id",""), "name": (p.get("displayName") or {}).get("text",""),
                "address": addr, "city": city, "state": sz[0] if sz else "",
                "zip": sz[1] if len(sz) > 1 else "", "phone": p.get("nationalPhoneNumber",""),
                "website": p.get("websiteUri",""), "email": "",
                "rating": p.get("rating"), "review_count": p.get("userRatingCount"),
                "listing_url": p.get("googleMapsUri",""), "hours": {},
            })
        return out
