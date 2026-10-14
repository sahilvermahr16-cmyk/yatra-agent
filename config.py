"""
All assumptions and settings in one place.

Live data: weather and coordinates (Open-Meteo), city popularity (Wikivoyage
pageviews), hotel names (OpenStreetMap). Everything below is assumed and is
reported in the "Assumptions" section of every trip report.
"""

# Group sharing (nights = days - 1 is applied in code)
PEOPLE_PER_ROOM = 2
PEOPLE_PER_VEHICLE = 4

# Defaults used only when the user does not say
DEFAULT_DAYS = 2
DEFAULT_TRAVELLERS = 1
DEFAULT_BUDGET_PER_PERSON_PER_DAY = 4000  # INR
DEFAULT_INTERESTS = ["popular"]
DEFAULT_START_OFFSET_DAYS = 1  # start tomorrow

# Budget meaning
BUDGET_FLEX = 0.10  # an "about" budget may be exceeded by up to 10%
PLAIN_BUDGET_DIRECTION = "at_most"  # a bare figure ("budget 20000") is treated as a maximum

# Limits
MAX_DAYS = 10
FORECAST_MAX_DAYS = 16  # Open-Meteo forecast horizon (today + 15 days)
# Search phrases used only by the default plan, when the planner's own plan cannot be used
DEFAULT_SEARCH_PHRASES = {
    "history": "historic site", "food": "food market", "nature": "park", "religious": "temple",
    "shopping": "market", "adventure": "adventure sports", "culture": "museum", "nightlife": "nightlife",
    "popular": "tourist attraction",
}
PLACES_PER_DAY = 3
RAINY_DAY_PROBABILITY = 60  # a day with at least this rain chance gets the most indoor places

# Assumed prices in INR (no free live price API exists for India).
# hotel: per room per night | food: per person per day | vehicle: per vehicle per day
PRICE_TABLE = {
    "budget": {"hotel_per_night": 1200, "food_per_day": 600, "vehicle_per_day": 800},
    "mid": {"hotel_per_night": 3000, "food_per_day": 1200, "vehicle_per_day": 1500},
    "luxury": {"hotel_per_night": 8000, "food_per_day": 2500, "vehicle_per_day": 3000},
}
DEFAULT_ENTRY_FEE = 100  # per person, when a place's fee is unknown
DEFAULT_STYLE = "mid"  # price level of the first draft when the user names none
PUBLIC_TRANSPORT_PER_PERSON_PER_DAY = 300  # buses, autos, shared cabs

# Places (Wikipedia search)
MUST_VISIT_RADIUS_KM = 60  # a must-visit place farther than this from the base city is not planned
SEARCH_RADIUS_KM = 25  # find_places searches within this distance of the base city
MAX_PLACES_PER_SEARCH = 6
POPULAR_CANDIDATES = 12  # the 'popular' text search returns this many results ...
NEARBY_RADIUS_KM = 10  # ... joined with every geotagged page this close to the centre (geosearch maximum)
NEARBY_LIMIT = 50
NEAR_CITY_RADIUS_KM = 10  # Wikipedia geosearch radius (its maximum) when finding the city a place is in
# Pages whose short description contains one of these are not sights (stations, schools, areas ...)
NOT_A_SIGHT_WORDS = [
    "railway station", "railway junction", "bus station", "airport", "metro station", "school", "college",
    "university", "institute", "hospital", "village", "district", "tehsil", "taluk", "constituency",
    "neighbourhood", "neighborhood", "suburb", "census town", "ward", "company", "bank", "hotel",
    "city in", "town in", "human settlement", "politician", "cricket ground", "stadium",
    "road", "locality", "residential", "shopping mall", "cinema", "office", "court", "police",
    "kingdom", "dynasty", "empire", "princely state", "historical state",
]
# Words that mean the visit happens outdoors; checked before INDOOR_WORDS ("Palace garden" is a garden)
OUTDOOR_WORDS = ["garden", "gardens", "park", "lake", "reservoir", "hill", "hills", "beach", "waterfall", "falls",
                 "zoo", "sanctuary", "valley", "dam", "ghat", "fort"]
# Words in a description that mean the visit happens mostly indoors (used on rainy days)
INDOOR_WORDS = [
    "museum", "temple", "palace", "mosque", "church", "cathedral", "gurudwara", "gurdwara", "gallery",
    "mausoleum", "tomb", "haveli", "monastery", "library", "theatre", "shrine", "dargah", "mall", "aquarium",
]

# Words that name a KIND of landmark, not a particular one: 'Amber Fort' is found by 'amber', 'City Palace' by 'city',
# so the town 'Amber, India' or the city page 'Udaipur' cannot pass for the place the user named
LANDMARK_WORDS = ["fort", "fortress", "palace", "temple", "mandir", "mahal", "lake", "garden", "gardens", "museum",
                  "mosque", "masjid", "church", "tomb", "ghat", "beach", "park", "market", "bazaar", "the", "of", "and"]
LOCATE_RESULTS = 5  # search results looked at when locating a must-visit place
POPULAR_MIN_VIEWS = 300  # a 'popular' sight needs a description and at least this many views in the window
# Soft preference: words in a must-visit place's description -> the kind of sight to prefer among popular ones
CATEGORY_WORDS = {
    "history": ["fort", "palace", "cenotaph", "museum", "monument", "tomb", "haveli", "stepwell", "ruins",
                "memorial", "mausoleum", "heritage"],
    "religious": ["temple", "mosque", "church", "gurudwara", "gurdwara", "shrine", "dargah", "monastery"],
    "nature": ["lake", "garden", "park", "waterfall", "hill", "beach", "sanctuary", "reservoir", "valley"],
    "shopping": ["market", "bazaar", "mall"],
}

# Stays and food (OpenStreetMap, Overpass API)
OSM_TIMEOUT_SECONDS = 25  # the time Overpass may spend on the query (it answers with an error after that) ...
OSM_CLIENT_TIMEOUT_SECONDS = 30  # ... so the agent waits a little longer than that
# Overpass servers, tried in order (python -m tools.osm compares them). In busy periods a server either refuses
# quickly (HTTP 429 / 504: asked once more after OSM_RETRY_WAIT_SECONDS) or does not answer in time (timeout: not
# asked again, the next server is). maps.mail.ru answered when the other three did not (2026-10-13 evening).
OSM_SERVERS = ["https://overpass-api.de/api/interpreter",
               "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
               "https://overpass.kumi.systems/api/interpreter",
               "https://overpass.private.coffee/api/interpreter"]
OSM_RETRY_WAIT_SECONDS = 3
HOTEL_SEARCH_KM = 8  # lodging is searched within this distance of each day's places
FOOD_SEARCH_KM = 2  # cafes and food stalls within this distance of each place
HOTEL_KEEP_KM = 3  # keep last night's hotel if it is this close to the next day's places
BREAKFAST_RADIUS_KM = 1.5  # breakfast near the day's first place
FOOD_STOP_RADIUS_KM = 2  # a food stop near the day's last place, only if the user asked for food
OUTSIDE_CENTRE_MIN_KM = 3  # 'stay outside the centre': a hotel this far from the next day's places ...
OUTSIDE_CENTRE_MAX_KM = 8  # ... but not farther than this
OUTSIDE_CENTRE_HOTEL_DISCOUNT = 0.25  # assumed: such a hotel costs 25% less
# Which OSM lodging fits each price level (stars only when OSM has them)
LODGING_FOR_TIER = {"budget": {"hostel", "guest_house"}, "mid": {"hotel"}, "luxury": {"hotel"}}

# The timed story of each day. Every duration is an assumption and is listed in the report.
# Times are minutes after midnight.
DAY_START = 9 * 60  # breakfast starts at 09:00
DAY_END = 19 * 60  # sightseeing should be over by 19:00; a place that does not fit moves to "if you have more time"
BREAKFAST_MINUTES = 45
BAG_MINUTES = 15  # dropping bags at the hotel desk (check-in is later) or collecting them
LUNCH_EARLIEST = 11 * 60 + 30  # lunch is never before 11:30 ...
LUNCH_FROM = 12 * 60 + 30  # ... it comes before the next visit once it is 12:30 ...
LUNCH_BY = 14 * 60 + 30  # ... or earlier, if the next visit would only end after 14:30
LUNCH_MINUTES = 60
REST_MINUTES = 60  # a rest after lunch, in the middle of the day (the user's wish)
DINNER_AT = 19 * 60 + 30  # the evening meal (street food if asked for, otherwise dinner)
DINNER_MINUTES = 60
MEAL_RADIUS_KM = 2  # lunch and dinner near where the traveller is at that time
FREE_TIME_MIN_MINUTES = 60  # a gap this long before dinner is shown as free time
CITY_SPEED_KMPH = 20  # average speed in city traffic
ROAD_FACTOR = 1.3  # roads are longer than the straight line between two places
TRAVEL_BUFFER_MINUTES = 10  # finding an auto or cab, parking, walking in
WALK_MAX_KM = 1.0  # up to this road distance the traveller walks ...
WALK_SPEED_KMPH = 4.5  # ... at this speed, with no buffer
# Time inside a place, not counting travel. First match on the place's name, then on its description.
VISIT_MINUTES = [
    (["fort", "fortress", "zoo", "safari", "sanctuary", "national park"], 150),
    (["palace"], 120),
    (["museum", "gallery", "market", "bazaar"], 90),
    (["temple", "mandir", "lake", "garden", "park", "beach", "dam", "ghat"], 60),
    (["cenotaph", "stepwell", "baori", "jhalra", "monument", "mosque", "tomb", "church", "memorial",
      "gurudwara", "gurdwara", "dargah"], 45),
    (["clock tower", "gate", "statue"], 30),
]
DEFAULT_VISIT_MINUTES = 60
# Which places go first when a day is too long or the budget too small; a must-visit place is never dropped
DROP_ORDER = ["popular", "interest", "place_type"]

# --inject-failure name -> tools that will time out on every attempt
INJECTABLE_FAILURES = {
    "weather_timeout": {"weather"},
    "places_timeout": {"places"},
    "geocode_timeout": {"geocode"},
    "osm_timeout": {"osm"},
}

# State -> base city
POPULARITY_WINDOW_DAYS = 60  # Wikivoyage pageviews window, counted in whole past months
POPULARITY_MAX_CANDIDATES = 12  # at most this many cities of a state are compared (one API call each)
# Used only if Wikivoyage is unreachable (state capital or main transport hub)
STATE_BASE_CITY_FALLBACK = {
    "andhra pradesh": "Visakhapatnam",
    "arunachal pradesh": "Itanagar",
    "assam": "Guwahati",
    "bihar": "Patna",
    "chhattisgarh": "Raipur",
    "goa": "Panaji",
    "gujarat": "Ahmedabad",
    "haryana": "Gurugram",
    "himachal pradesh": "Shimla",
    "jharkhand": "Ranchi",
    "karnataka": "Bengaluru",
    "kerala": "Kochi",
    "madhya pradesh": "Bhopal",
    "maharashtra": "Mumbai",
    "manipur": "Imphal",
    "meghalaya": "Shillong",
    "mizoram": "Aizawl",
    "nagaland": "Kohima",
    "odisha": "Bhubaneswar",
    "punjab": "Amritsar",
    "rajasthan": "Jaipur",
    "sikkim": "Gangtok",
    "tamil nadu": "Chennai",
    "telangana": "Hyderabad",
    "tripura": "Agartala",
    "uttar pradesh": "Lucknow",
    "uttarakhand": "Dehradun",
    "west bengal": "Kolkata",
    "andaman and nicobar islands": "Port Blair",
    "dadra and nagar haveli and daman and diu": "Daman",
    "jammu and kashmir": "Srinagar",
    "ladakh": "Leh",
    "lakshadweep": "Kavaratti",
}
# Union territories that are a single city: planned as a city, never as a state
CITY_LIKE_UTS = {"delhi", "chandigarh", "puducherry"}
# Other names people use for a state or UT
STATE_ALIASES = {
    "j&k": "jammu and kashmir",
    "j and k": "jammu and kashmir",
    "kashmir": "jammu and kashmir",
    "pondicherry": "puducherry",
    "pondy": "puducherry",
    "orissa": "odisha",
    "uttaranchal": "uttarakhand",
    "andaman": "andaman and nicobar islands",
    "andamans": "andaman and nicobar islands",
    "andaman islands": "andaman and nicobar islands",
    "new delhi": "delhi",
}

# 28 states + 8 union territories
INDIAN_STATES_AND_UTS = {
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh", "goa",
    "gujarat", "haryana", "himachal pradesh", "jharkhand", "karnataka", "kerala",
    "madhya pradesh", "maharashtra", "manipur", "meghalaya", "mizoram", "nagaland",
    "odisha", "punjab", "rajasthan", "sikkim", "tamil nadu", "telangana", "tripura",
    "uttar pradesh", "uttarakhand", "west bengal",
    "andaman and nicobar islands", "chandigarh", "dadra and nagar haveli and daman and diu",
    "delhi", "jammu and kashmir", "ladakh", "lakshadweep", "puducherry",
}

# Geocoding: when several matches exist, prefer the more important place
GEOCODE_COUNTRY = "IN"
GEOCODE_FEATURE_PRIORITY = ["PPLC", "PPLA", "PPLA2", "PPLA3", "PPL"]
AMBIGUOUS_MIN_POPULATION_SHARE = 0.05  # a namesake smaller than 5% of the chosen place is not worth a note
GEOCODE_TRUST_KM = 50  # a geocoding match this close to the Wikivoyage page's coordinates is the place meant

# Tool reliability
TOOL_TIMEOUT_SECONDS = 8
TOOL_RETRIES = 2
MAX_REPLANS = 3
HTTP_USER_AGENT = "yatra-agent/0.1 (Xiarch assignment; sahilvermahr16@gmail.com)"

# LLM
LLM_MODEL = "gpt-4o-mini"
LLM_TEMPERATURE = 0
