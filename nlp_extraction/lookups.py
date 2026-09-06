"""
Vocabulary the extractor matches against. Kept separate from
extractor.py so it's easy to extend without touching matching logic —
e.g. adding a new occupation is a one-line addition here.

Values on the right are the NORMALIZED forms — they must match
whatever normalization your scraped scheme data uses in
`EligibilityCriteria.occupation` / `.state` / `.caste_category`
(schema.py normalizes state/occupation as lowercase strings; caste
category is an enum). Keeping extraction and scheme-data
normalization consistent is what lets the rule engine compare them
with a simple string/enum equality check.
"""

INDIAN_STATES = [
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh",
    "goa", "gujarat", "haryana", "himachal pradesh", "jharkhand",
    "karnataka", "kerala", "madhya pradesh", "maharashtra", "manipur",
    "meghalaya", "mizoram", "nagaland", "odisha", "punjab", "rajasthan",
    "sikkim", "tamil nadu", "telangana", "tripura", "uttar pradesh",
    "uttarakhand", "west bengal", "delhi", "jammu and kashmir", "ladakh",
    "puducherry", "chandigarh",
]

# surface phrase -> normalized occupation value (matches EligibilityCriteria.occupation)
OCCUPATION_TERMS = {
    "farmer": "farmer",
    "farming": "farmer",
    "agricultural laborer": "landless_laborer",
    "landless laborer": "landless_laborer",
    "landless labourer": "landless_laborer",
    "laborer": "laborer",
    "labourer": "laborer",
    "daily wage worker": "laborer",
    "construction worker": "construction_worker",
    "domestic worker": "domestic_worker",
    "housemaid": "domestic_worker",
    "teacher": "teacher",
    "driver": "driver",
    "auto driver": "driver",
    "shopkeeper": "shopkeeper",
    "small business owner": "shopkeeper",
    "artisan": "artisan",
    "weaver": "artisan",
    "fisherman": "fisherman",
    "fisherwoman": "fisherman",
    "street vendor": "street_vendor",
    "unemployed": "unemployed",
    "student": "student",
    "government employee": "government_employee",
    "govt employee": "government_employee",
    "private employee": "private_employee",
    "self employed": "self_employed",
    "self-employed": "self_employed",
}

# surface phrase -> normalized CasteCategory enum value
CASTE_TERMS = {
    "scheduled caste": "sc",
    "scheduled tribe": "st",
    "other backward class": "obc",
    "other backward classes": "obc",
    "backward class": "obc",
    "economically weaker section": "ews",
    "general category": "general",
    "unreserved category": "general",
    "obc": "obc",
    "sc": "sc",
    "st": "st",
    "ews": "ews",
}

MARITAL_TERMS = {
    "unmarried": "unmarried",
    "single": "unmarried",
    "married": "married",
    "widow": "widowed",
    "widower": "widowed",
    "widowed": "widowed",
    # divorced has no dedicated enum value yet — mapped to "unmarried" as
    # the closest fit (not currently married). Documented limitation;
    # add a DIVORCED value to schema.MaritalStatus if a scheme actually
    # distinguishes it.
    "divorced": "unmarried",
}

GENDER_TERMS = {
    "male": "male",
    "man": "male",
    "boy": "male",
    "female": "female",
    "woman": "female",
    "girl": "female",
    # gendered marital-status words also imply gender
    "widow": "female",
    "widower": "male",
}

DISABILITY_TERMS = [
    "disability", "disabled", "differently abled", "differently-abled",
    "handicapped", "pwd", "person with disability",
]

BPL_TERMS = [
    "bpl card", "bpl", "below poverty line",
]
