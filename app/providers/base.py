class ProviderNotConfigured(Exception):
    pass

class ProviderError(Exception):
    pass

class BaseProvider:
    name = "base"
    cost_per_request_usd = 0.0
    def is_configured(self): return False
    def search(self, *, term, location, limit=20):
        """Return list of normalized dicts:
        {provider_id,name,address,city,state,zip,phone,website,email,rating,review_count,listing_url,hours}
        Missing fields must be ''/None — never fabricated."""
        raise NotImplementedError
