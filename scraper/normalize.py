"""Turn whatever JSON a portal returns into one standard listing shape.

Portals rename fields often, so instead of hard-coding one schema we look
for each standard field under a list of likely key names. If BAANKNET
changes a key, add the new name to FIELD_CANDIDATES — nothing else changes.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

# standard field -> possible source keys (case/underscore-insensitive)
FIELD_CANDIDATES = {
    "id": ["propertyId", "property_id", "propertyid", "id", "auctionId", "listingId", "assetId", "refNo", "propertyCode"],
    "bank": ["bankName", "bank", "lenderName", "lender", "institutionName", "orgName", "sellerName"],
    "title": ["propertyTitle", "title", "propertyName", "name", "assetName", "description", "propertyDescription"],
    "property_type": ["propertyType", "propertyTypeName", "assetType", "assetCategory", "category", "propertySubType", "subCategory", "type"],
    "state": ["state", "stateName", "propertyState"],
    "city": ["city", "cityName", "district", "districtName", "propertyCity", "location"],
    "address": ["address", "propertyAddress", "fullAddress", "locality", "area", "addressLine1"],
    "pincode": ["pincode", "pinCode", "pin", "zip", "postalCode"],
    "reserve_price": ["reservePrice", "reserve_price", "reservePriceAmount", "basePrice", "price", "minimumBid", "reserveprice"],
    "emd": ["emd", "emdAmount", "earnestMoney", "earnestMoneyDeposit"],
    "auction_date": ["auctionDate", "auctionStartDate", "auctionStartDateTime", "startDate", "eAuctionDate", "auction_start", "bidStartDate"],
    "emd_last_date": ["emdLastDate", "emdSubmissionDate", "applicationDeadline", "lastDateOfEmd", "emdEndDate"],
    "possession": ["possession", "possessionType", "possessionStatus", "typeOfPossession"],
    "area": ["area", "propertyArea", "builtUpArea", "carpetArea", "plotArea", "size", "propertySize"],
    "auction_type": ["auctionType", "saleType", "act"],
    "contact": ["contactNumber", "contact", "officerContact", "mobile", "phone", "authorisedOfficerContact"],
    "url": ["url", "propertyUrl", "detailUrl", "link", "shareUrl"],
}

DATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y",
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y",
]


def _key(k: str) -> str:
    return re.sub(r"[^a-z0-9]", "", k.lower())


def flatten(obj, prefix="", out=None):
    """Nested dicts -> {'leafkey': value}; first occurrence of a leaf key wins."""
    if out is None:
        out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                if isinstance(v, dict):
                    flatten(v, prefix + k + ".", out)
                elif v and all(not isinstance(i, (dict, list)) for i in v):
                    out.setdefault(_key(k), ", ".join(str(i) for i in v))
            else:
                out.setdefault(_key(k), v)
    return out


def pick(flat: dict, field: str):
    for cand in FIELD_CANDIDATES[field]:
        v = flat.get(_key(cand))
        if v not in (None, "", "null", "NA", "N/A"):
            return v
    return None


def to_number(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).lower().replace(",", "").replace("₹", "").replace("rs.", "").replace("inr", "").strip()
    mult = 1
    if "crore" in s or s.endswith("cr"):
        mult = 1e7
    elif "lakh" in s or "lac" in s or s.endswith("l"):
        mult = 1e5
    m = re.search(r"\d+(\.\d+)?", s)
    return float(m.group()) * mult if m else None


def to_iso_date(v):
    if v is None:
        return None
    if isinstance(v, (int, float)) and v > 1e9:  # epoch seconds / ms
        ts = v / 1000 if v > 1e12 else v
        return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M")
    s = str(v).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            continue
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) + "T00:00" if m else None


def clean_type(t):
    if not t:
        return "Other"
    t = str(t).strip().lower()
    rules = [
        ("Flat / Apartment", ["flat", "apartment"]),
        ("House / Villa", ["house", "villa", "bungalow", "independent", "row house"]),
        ("Plot / Land", ["plot", "land", "site", "agricultur"]),
        ("Commercial", ["shop", "office", "commercial", "showroom", "godown", "warehouse"]),
        ("Industrial", ["industrial", "factory", "shed"]),
        ("Vehicle / Machinery", ["vehicle", "car", "machinery", "plant"]),
    ]
    for label, words in rules:
        if any(w in t for w in words):
            return label
    return str(t).title()[:40]


def normalize(raw: dict, source: str, base_url: str = "") -> dict | None:
    flat = flatten(raw)
    rec = {f: pick(flat, f) for f in FIELD_CANDIDATES}
    rec["reserve_price"] = to_number(rec["reserve_price"])
    rec["emd"] = to_number(rec["emd"])
    rec["auction_date"] = to_iso_date(rec["auction_date"])
    rec["emd_last_date"] = to_iso_date(rec["emd_last_date"])
    rec["property_type"] = clean_type(rec["property_type"] or rec["title"])
    for f in ("state", "city", "bank"):
        if rec[f]:
            rec[f] = str(rec[f]).strip().title()
    if not rec["reserve_price"] and not rec["auction_date"]:
        return None  # not a property listing
    if not rec["id"]:
        rec["id"] = hashlib.md5(repr(sorted(flat.items())).encode()).hexdigest()[:12]
    rec["id"] = f"{source}:{rec['id']}"
    rec["source"] = source
    if rec["url"] and base_url and str(rec["url"]).startswith("/"):
        rec["url"] = base_url.rstrip("/") + rec["url"]
    return rec


def looks_like_listing(d: dict) -> bool:
    flat = flatten(d)
    return pick(flat, "reserve_price") is not None and (
        pick(flat, "city") is not None or pick(flat, "state") is not None
    )


def find_listing_arrays(payload, path="$"):
    """Yield (path, list_of_dicts) for arrays in a JSON payload that hold listings."""
    if isinstance(payload, list):
        dicts = [x for x in payload if isinstance(x, dict)]
        if dicts and sum(looks_like_listing(x) for x in dicts[:5]) >= min(2, len(dicts)):
            yield path, dicts
            return
        for i, x in enumerate(payload[:3]):
            yield from find_listing_arrays(x, f"{path}[{i}]")
    elif isinstance(payload, dict):
        for k, v in payload.items():
            yield from find_listing_arrays(v, f"{path}.{k}")
