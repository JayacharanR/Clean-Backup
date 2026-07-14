"""
Category taxonomy for content-based image classification.

This is the single source of truth for all classification categories.
Categories are data-driven (not hardcoded if/else chains) and are seeded
into the SQLite ``categories`` table on first run.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Full taxonomy — order matters for seeding (id will be auto-incremented)
# ---------------------------------------------------------------------------

CATEGORY_TAXONOMY: list[dict] = [
    {
        "key": "videos",
        "label": "Videos",
        "priority": 0,
        "default_enabled": True,
        "detection": "filesystem",
    },
    {
        "key": "documents",
        "label": "Documents",
        "priority": 1,
        "default_enabled": True,
        "detection": "heuristic",
    },
    {
        "key": "screenshots",
        "label": "Screenshots",
        "priority": 1,
        "default_enabled": True,
        "detection": "heuristic",
    },
    {
        "key": "people",
        "label": "People",
        "priority": 2,
        "default_enabled": True,
        "detection": "ml_face",
    },
    {
        "key": "travel",
        "label": "Travel",
        "priority": 2,
        "default_enabled": True,
        "detection": "exif+ml",
    },
    {
        "key": "family",
        "label": "Family",
        "priority": 3,
        "default_enabled": True,
        "detection": "face+scene",
    },
    {
        "key": "selfies",
        "label": "Selfies",
        "priority": 3,
        "default_enabled": False,
        "detection": "face_bbox",
    },
    {
        "key": "events",
        "label": "Events",
        "priority": 3,
        "default_enabled": True,
        "detection": "face+exif",
    },
    {
        "key": "nature",
        "label": "Nature / Scenery",
        "priority": 4,
        "default_enabled": True,
        "detection": "ml_scene",
    },
    {
        "key": "food",
        "label": "Food",
        "priority": 4,
        "default_enabled": False,
        "detection": "ml_scene",
    },
    {
        "key": "pets",
        "label": "Pets / Animals",
        "priority": 4,
        "default_enabled": False,
        "detection": "ml_scene",
    },
    {
        "key": "vehicles",
        "label": "Vehicles",
        "priority": 5,
        "default_enabled": False,
        "detection": "ml_scene",
    },
    {
        "key": "art",
        "label": "Art / Architecture",
        "priority": 5,
        "default_enabled": False,
        "detection": "ml_scene",
    },
    {
        "key": "night",
        "label": "Night / Landscape",
        "priority": 5,
        "default_enabled": False,
        "detection": "exif+ml",
    },
    {
        "key": "other",
        "label": "Other / Unclassified",
        "priority": 99,
        "default_enabled": True,
        "detection": "fallback",
    },
]

# ---------------------------------------------------------------------------
# Common screen resolutions for screenshot detection (width, height)
# Includes common desktop, laptop, tablet and phone resolutions
# ---------------------------------------------------------------------------

SCREEN_RESOLUTIONS: set[tuple[int, int]] = {
    # Desktop / Laptop
    (1920, 1080), (1080, 1920),
    (2560, 1440), (1440, 2560),
    (3840, 2160), (2160, 3840),
    (1366, 768),  (768, 1366),
    (1440, 900),  (900, 1440),
    (1680, 1050), (1050, 1680),
    (1280, 720),  (720, 1280),
    (1280, 800),  (800, 1280),
    (1600, 900),  (900, 1600),
    (2560, 1600), (1600, 2560),
    (3440, 1440), (1440, 3440),
    (2560, 1080), (1080, 2560),
    # Apple Retina
    (2880, 1800), (1800, 2880),
    (3024, 1964), (1964, 3024),
    (2048, 1536), (1536, 2048),
    (5120, 2880), (2880, 5120),
    # iPhone
    (750, 1334),  (1334, 750),
    (1125, 2436), (2436, 1125),
    (1170, 2532), (2532, 1170),
    (1179, 2556), (2556, 1179),
    (1284, 2778), (2778, 1284),
    (1290, 2796), (2796, 1290),
    (828, 1792),  (1792, 828),
    (1242, 2688), (2688, 1242),
    # Android common
    (1080, 2400), (2400, 1080),
    (1080, 2340), (2340, 1080),
    (1440, 3200), (3200, 1440),
    (1440, 3120), (3120, 1440),
    (1080, 1920), (1920, 1080),
    # Tablets
    (2732, 2048), (2048, 2732),
    (2360, 1640), (1640, 2360),
    (2388, 1668), (1668, 2388),
}

# ---------------------------------------------------------------------------
# ImageNet class-index → category key mapping
# One inference pass maps to zero or more categories via this table.
# Indices reference the standard ImageNet-1000 class list.
# ---------------------------------------------------------------------------

SCENE_CLASS_MAP: dict[int, str] = {}

# Nature / Scenery — landscape, outdoor natural scenes
_nature_indices = [
    970, 971, 972, 973, 974, 975, 976, 979, 980,  # alp, cliff, coral reef, geyser, lakeside, promontory, sandbar, valley, volcano
    846, 847, 848, 849, 850,  # seashore related
    975,  # promontory
    331, 332,  # not animals — general outdoor
]
for _i in _nature_indices:
    SCENE_CLASS_MAP[_i] = "nature"

# Food — food items, dining
_food_indices = [
    924, 925, 926, 927, 928, 929, 930, 931, 932, 933, 934, 935, 936, 937, 938, 939, 940, 941, 942, 943, 944, 945, 946, 947, 948, 949, 950, 951, 952, 953, 954, 955, 956, 957, 958, 959, 960, 961, 962, 963, 964, 965, 966, 967, 968, 969,
    # Specific food items
    567,  # frying pan
    968,  # cup
    504,  # coffee mug
    809,  # soup bowl
    899,  # water bottle
]
for _i in _food_indices:
    SCENE_CLASS_MAP[_i] = "food"

# Pets / Animals — dogs, cats, birds, etc.
_pet_indices = list(range(151, 269))  # dog breeds
_pet_indices += list(range(281, 286))  # cat breeds
_pet_indices += list(range(7, 25))    # birds
_pet_indices += [0, 1, 2, 3, 4, 5, 6]  # fish
_pet_indices += list(range(30, 70))   # various animals
for _i in _pet_indices:
    SCENE_CLASS_MAP[_i] = "pets"

# Vehicles
_vehicle_indices = [
    407, 436, 468, 511, 555, 569, 573, 574, 575, 609, 627, 654, 656, 665, 670, 675, 705, 717, 734, 751, 779, 817, 864, 867, 874,
    # 407=ambulance, 436=beach_wagon, 468=cab, 511=convertible, 555=fire_engine,
    # 569=freight_car, 573=garbage_truck, 609=jeep, 627=limousine, 654=minivan,
    # 665=motor_scooter, 670=mountain_bike, 675=moped, 705=passenger_car,
    # 717=pickup, 734=police_van, 751=racer, 779=school_bus, 817=sports_car,
    # 864=tow_truck, 867=trailer_truck, 874=trolleybus
    404,  # airliner
    895,  # warplane
    510,  # container_ship
    628,  # lifeboat
    724,  # pirate_ship
    814,  # speedboat
]
for _i in _vehicle_indices:
    SCENE_CLASS_MAP[_i] = "vehicles"

# Art / Architecture — buildings, monuments, museums
_art_indices = [
    497, 536, 538, 539, 540, 541, 556, 575, 576, 577, 663, 668, 669, 698, 725, 726, 727, 728, 730, 732, 743, 797, 831, 832, 833, 834, 835, 836, 838,
    # 497=church, 536=dock, 538=dome, 556=fire_screen, 663=monastery,
    # 668=mosque, 669=mound, 698=palace, 725=pier, 832=stupa, 833=submarine
    483,  # castle
    576,  # gondola
    836,  # suspension_bridge
]
for _i in _art_indices:
    SCENE_CLASS_MAP[_i] = "art"

# Travel (ML fallback) — airport, resort, landmarks
_travel_ml_indices = [
    405,  # airship
    449,  # beacon / lighthouse
    694,  # padlock
]
for _i in _travel_ml_indices:
    SCENE_CLASS_MAP[_i] = "travel"

# ---------------------------------------------------------------------------
# EXIF keywords that suggest Travel
# ---------------------------------------------------------------------------

TRAVEL_KEYWORDS: set[str] = {
    "travel", "vacation", "holiday", "trip", "airport", "flight",
    "beach", "resort", "hotel", "motel", "hostel", "tourism",
    "landmark", "monument", "sightseeing", "cruise", "backpacking",
    "abroad", "international", "passport", "hiking", "camping",
    "temple", "cathedral", "museum", "national park",
}

# ---------------------------------------------------------------------------
# EXIF keywords that suggest Events
# ---------------------------------------------------------------------------

EVENT_KEYWORDS: set[str] = {
    "birthday", "wedding", "party", "celebration", "anniversary",
    "graduation", "ceremony", "festival", "concert", "reunion",
    "christmas", "new year", "thanksgiving", "easter", "halloween",
    "baby shower", "engagement", "reception", "prom", "gala",
}

# ---------------------------------------------------------------------------
# UI icon map (emoji) for frontend display
# ---------------------------------------------------------------------------

CATEGORY_ICONS: dict[str, str] = {
    "videos": "🎥",
    "documents": "📄",
    "screenshots": "🖥️",
    "people": "👤",
    "travel": "✈️",
    "family": "👨‍👩‍👧‍👦",
    "selfies": "🤳",
    "events": "🎉",
    "nature": "🌿",
    "food": "🍽️",
    "pets": "🐾",
    "vehicles": "🚗",
    "art": "🏛️",
    "night": "🌙",
    "other": "📁",
}
