from .google_places import GooglePlacesProvider
from .yelp import YelpProvider
from .synthetic import SyntheticProvider

def get_provider(name):
    return {"google_places": GooglePlacesProvider, "yelp": YelpProvider,
            "synthetic_test": SyntheticProvider}.get(name, GooglePlacesProvider)()
