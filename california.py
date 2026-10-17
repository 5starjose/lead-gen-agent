"""California region presets for statewide scanning.

One campaign per region keeps daily caps and budgets manageable: a single
campaign covering every California city would either blow through its daily
Google Places budget on the first few cities or never get past them (the
runner walks cities in order). Regional campaigns also stagger their daily
schedule times so the runs do not all fire at once.

City lists are major populated places per region (real cities only). They are
starting points — Jose can edit any regional campaign's city list from the
Campaigns page after creating it.
"""
import re

# Insertion order matters: it defines the stagger order below.
CA_REGIONS = {
    "Los Angeles Metro": [
        "Los Angeles", "Long Beach", "Glendale", "Pasadena", "Burbank",
        "Santa Monica", "Inglewood", "Downey", "Torrance", "Whittier",
        "Arcadia", "El Monte", "West Covina",
    ],
    "Inland Empire": [
        "Pomona", "Ontario", "Rancho Cucamonga", "Riverside", "San Bernardino",
        "Fontana", "Upland", "Claremont", "Chino", "Corona",
        "Moreno Valley", "Redlands",
    ],
    "Orange County": [
        "Anaheim", "Santa Ana", "Irvine", "Fullerton", "Huntington Beach",
        "Costa Mesa", "Mission Viejo", "Orange", "Garden Grove", "Lake Forest",
    ],
    "San Diego County": [
        "San Diego", "Chula Vista", "Oceanside", "Carlsbad", "Escondido",
        "El Cajon", "Encinitas", "La Mesa", "Vista", "San Marcos",
    ],
    "Ventura & Santa Barbara": [
        "Ventura", "Oxnard", "Thousand Oaks", "Simi Valley", "Camarillo",
        "Moorpark", "Santa Paula", "Santa Barbara", "Goleta", "Carpinteria",
    ],
    "Central Coast": [
        "Santa Maria", "San Luis Obispo", "Paso Robles", "Atascadero",
        "Arroyo Grande", "Monterey", "Salinas", "Santa Cruz", "Watsonville",
        "Hollister",
    ],
    "Central Valley South": [
        "Fresno", "Bakersfield", "Visalia", "Clovis", "Merced",
        "Hanford", "Tulare", "Porterville", "Delano", "Madera",
    ],
    "Central Valley North": [
        "Stockton", "Modesto", "Tracy", "Manteca", "Turlock",
        "Lodi", "Ceres", "Riverbank",
    ],
    "Sacramento Metro": [
        "Sacramento", "Roseville", "Folsom", "Elk Grove", "Citrus Heights",
        "Rancho Cordova", "Davis", "Woodland", "Rocklin", "West Sacramento",
    ],
    "Bay Area": [
        "San Francisco", "Oakland", "San Jose", "Fremont", "Santa Clara",
        "Sunnyvale", "Berkeley", "Richmond", "Walnut Creek", "Concord",
        "Santa Rosa", "Petaluma", "Napa", "Vallejo", "San Rafael",
    ],
    "Far North": [
        "Redding", "Chico", "Eureka", "Yuba City", "Marysville",
        "Oroville", "Paradise", "Red Bluff", "Arcata", "Anderson",
    ],
}

FIRST_RUN_TIME = "06:00"   # first region's daily schedule time (local)
STAGGER_MINUTES = 20       # each later region starts this much later


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def schedule_time_for(index: int) -> str:
    """Staggered daily start: 06:00, 06:20, 06:40, ... for index 0, 1, 2, ..."""
    hh, mm = (int(x) for x in FIRST_RUN_TIME.split(":"))
    total = hh * 60 + mm + index * STAGGER_MINUTES
    return f"{total // 60 % 24:02d}:{total % 60:02d}"


def region_list():
    """Template/API friendly view: [{slug, name, cities, schedule_time}]."""
    return [{"slug": slugify(name), "name": name, "cities": cities,
             "schedule_time": schedule_time_for(i)}
            for i, (name, cities) in enumerate(CA_REGIONS.items())]


def region_by_slug(slug: str):
    for region in region_list():
        if region["slug"] == slug:
            return region
    return None


def campaign_name_for(region_name: str) -> str:
    return f"California — {region_name}"
