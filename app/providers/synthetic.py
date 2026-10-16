"""Synthetic/test provider — TEST ONLY. Returns clearly-labeled fake records.
Refuses to run unless APP_ENV=test (hard env separation; never mixed into live leads)."""
from .base import BaseProvider, ProviderNotConfigured
from ..config import get_settings

class SyntheticProvider(BaseProvider):
    name = "synthetic_test"
    cost_per_request_usd = 0.0
    def is_configured(self): return get_settings().synthetic_allowed
    def search(self, *, term, location, limit=20):
        if not self.is_configured():
            raise ProviderNotConfigured("synthetic_test: only available when APP_ENV=test")
        city = location.split(",")[0].strip() or "Testville"
        return [{
            "provider_id": f"synthetic-{term[:6]}-1", "name": f"SYNTHETIC TEST {term.title()} Co",
            "address": "1 Test Way", "city": city, "state": "CA", "zip": "00000",
            "phone": "(555) 010-0001", "website": "", "email": "",
            "rating": 4.6, "review_count": 42, "listing_url": "", "hours": {},
        }][:limit]
