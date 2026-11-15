"""Pull listing fields out of free text (PDF sale notices, HTML cards).

Sale notices are not standard, so this is best-effort: every record made
here is marked approx=True and the site tells users to open the notice.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from normalize import clean_type

# first 2 digits of a PIN code -> state
PIN_STATE = {
    **{p: "Delhi" for p in ("11",)}, **{p: "Haryana" for p in ("12", "13")}, **{p: "Punjab" for p in ("14", "15")},
    "16": "Chandigarh", "17": "Himachal Pradesh", **{p: "Jammu And Kashmir" for p in ("18", "19")},
    **{p: "Uttar Pradesh" for p in ("20", "21", "22", "23", "24", "25", "26", "27", "28")},
    "24": "Uttarakhand", "26": "Uttarakhand",
    **{p: "Rajasthan" for p in ("30", "31", "32", "33", "34")},
    **{p: "Gujarat" for p in ("36", "37", "38", "39")}, "396": "Dadra And Nagar Haveli",
    **{p: "Maharashtra" for p in ("40", "41", "42", "43", "44")}, "403": "Goa",
    **{p: "Madhya Pradesh" for p in ("45", "46", "47", "48")}, "49": "Chhattisgarh",
    **{p: "Telangana" for p in ("50",)}, **{p: "Andhra Pradesh" for p in ("51", "52", "53")},
    **{p: "Karnataka" for p in ("56", "57", "58", "59")},
    **{p: "Tamil Nadu" for p in ("60", "61", "62", "63", "64")}, "605": "Puducherry",
    **{p: "Kerala" for p in ("67", "68", "69")},
    **{p: "West Bengal" for p in ("70", "71", "72", "73", "74")}, "737": "Sikkim",
    **{p: "Odisha" for p in ("75", "76", "77")}, "78": "Assam", "79": "North East",
    **{p: "Bihar" for p in ("80", "81", "82", "84", "85")}, "83": "Jharkhand",
}

CITIES = """Bengaluru|Bangalore|Mysuru|Mysore|Mangaluru|Mangalore|Hubballi|Hubli|Dharwad|Belagavi|Belgaum|Kalaburagi|Davanagere|Shivamogga|Tumakuru|Udupi|Ballari
|Mumbai|Navi Mumbai|Thane|Pune|Nagpur|Nashik|Aurangabad|Chhatrapati Sambhajinagar|Solapur|Kolhapur|Palghar|Kalyan|Vasai|Panvel|Amravati|Sangli
|Chennai|Coimbatore|Madurai|Tiruchirappalli|Trichy|Salem|Tiruppur|Erode|Vellore|Tirunelveli|Kanchipuram|Chengalpattu|Hosur|Thiruvallur
|Hyderabad|Secunderabad|Warangal|Karimnagar|Nizamabad|Khammam|Rangareddy|Medchal
|Visakhapatnam|Vijayawada|Guntur|Nellore|Tirupati|Kurnool|Kakinada|Rajahmundry|Anantapur
|Kochi|Ernakulam|Thiruvananthapuram|Trivandrum|Kozhikode|Calicut|Thrissur|Kollam|Kottayam|Palakkad|Kannur|Malappuram|Alappuzha
|New Delhi|Delhi|Gurugram|Gurgaon|Faridabad|Noida|Greater Noida|Ghaziabad|Sonipat|Panipat|Karnal|Ambala|Rohtak|Hisar|Panchkula
|Ahmedabad|Surat|Vadodara|Rajkot|Gandhinagar|Bhavnagar|Jamnagar|Anand|Vapi|Bharuch
|Jaipur|Jodhpur|Udaipur|Kota|Ajmer|Bikaner|Alwar|Bhilwara
|Lucknow|Kanpur|Agra|Varanasi|Prayagraj|Allahabad|Meerut|Bareilly|Aligarh|Gorakhpur|Moradabad
|Kolkata|Howrah|Siliguri|Durgapur|Asansol|24 Parganas|Hooghly
|Bhopal|Indore|Gwalior|Jabalpur|Ujjain|Raipur|Bilaspur|Bhilai
|Chandigarh|Mohali|Ludhiana|Amritsar|Jalandhar|Patiala|Bathinda
|Patna|Gaya|Muzaffarpur|Ranchi|Jamshedpur|Dhanbad|Bhubaneswar|Cuttack|Guwahati|Dehradun|Haridwar|Shimla|Jammu|Srinagar|Goa|Panaji|Margao"""
CITY_RE = re.compile(r"\b(" + CITIES.replace("\n", "") + r")\b", re.I)
CANON = {"bangalore": "Bengaluru", "mysore": "Mysuru", "mangalore": "Mangaluru", "hubli": "Hubballi", "belgaum": "Belagavi",
         "gurgaon": "Gurugram", "trivandrum": "Thiruvananthapuram", "calicut": "Kozhikode", "trichy": "Tiruchirappalli",
         "allahabad": "Prayagraj", "kochi": "Ernakulam", "secunderabad": "Hyderabad", "aurangabad": "Chhatrapati Sambhajinagar"}
STATES = ["Andhra Pradesh", "Assam", "Bihar", "Chhattisgarh", "Delhi", "Goa", "Gujarat", "Haryana", "Himachal Pradesh",
          "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Odisha", "Punjab", "Rajasthan", "Tamil Nadu",
          "Telangana", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Jammu And Kashmir", "Chandigarh", "Puducherry"]
OFFICE_LINE = re.compile(r"head office|registered office|regd\.? office|corporate office|cin\s*[:\-]?\s*[lu]\d|website|www\.|e-?mail|ifsc", re.I)

AMT = r"(?:rs\.?|₹|inr)?\s*([0-9]{1,3}(?:,[0-9]{2,3})+(?:\.\d+)?|[0-9]{5,}(?:\.\d+)?)\s*(?:/-)?\s*(lakhs?|lacs?|crores?|cr)?"
MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
DATE_PATTERNS = [
    (re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b"), "dmy"),
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+(" + MONTHS + r")[a-z]*[\s,\-]+(20\d{2})\b", re.I), "dMy"),
    (re.compile(r"\b(" + MONTHS + r")[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b", re.I), "Mdy"),
]
MON = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _amount(num: str, unit: str | None) -> float | None:
    try:
        v = float(num.replace(",", ""))
    except ValueError:
        return None
    u = (unit or "").lower()
    if u.startswith(("lakh", "lac")):
        v *= 1e5
    elif u.startswith(("crore", "cr")):
        v *= 1e7
    return v if 10_000 <= v <= 5e10 else None


def amount_after(text: str, label: str, window: int = 260):
    for m in re.finditer(label, text, re.I):
        seg = text[m.end(): m.end() + window]
        for a in re.finditer(AMT, seg, re.I):
            v = _amount(a.group(1), a.group(2))
            if v:
                return v
    return None


def dates_in(text: str):
    out = []
    for rx, kind in DATE_PATTERNS:
        for m in rx.finditer(text):
            try:
                if kind == "dmy":
                    d = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                elif kind == "dMy":
                    d = datetime(int(m.group(3)), MON[m.group(2).lower()[:3]], int(m.group(1)))
                else:
                    d = datetime(int(m.group(3)), MON[m.group(1).lower()[:3]], int(m.group(2)))
            except (ValueError, KeyError):
                continue
            out.append((m.start(), d))
    return sorted(out)


def auction_date(text: str):
    ds = dates_in(text)
    if not ds:
        return None
    for lab in re.finditer(r"(date\s*(?:&|and)?\s*time\s*of\s*(?:the\s*)?(?:public\s*)?e-?\s*auction|date\s*of\s*(?:e-?\s*)?auction|e-?\s*auction\s*(?:date|on|will be held on)|auction\s*(?:date|on|schedule))", text, re.I):
        near = [d for pos, d in ds if lab.end() <= pos <= lab.end() + 250]
        if near:
            return near[0].strftime("%Y-%m-%dT%H:%M")
    # fallback: latest date in the plausible future window
    now = datetime.now()
    fut = [d for _, d in ds if now - timedelta(days=30) <= d <= now + timedelta(days=180)]
    return max(fut).strftime("%Y-%m-%dT%H:%M") if fut else None


def location(text: str):
    body = "\n".join(l for l in text.splitlines() if not OFFICE_LINE.search(l))
    counts: dict[str, int] = {}
    for m in CITY_RE.finditer(body):
        c = m.group(1).strip()
        c = CANON.get(c.lower(), c.title())
        counts[c] = counts.get(c, 0) + 1
    city = max(counts, key=counts.get) if counts else None
    # prefer the city named in the property description itself
    m = re.search(r"(description of (?:the )?(?:immovable )?propert|details of (?:the )?(?:immovable )?propert|property address|all that (?:piece|part)|situated at)", body, re.I)
    if m:
        cm = CITY_RE.search(body[m.end(): m.end() + 700])
        if cm:
            city = CANON.get(cm.group(1).lower(), cm.group(1).title())
    pins = re.findall(r"(?<!\d)([1-8]\d{2})\s?(\d{3})(?!\d)", body)
    pincode = state = None
    if pins:
        pincode = pins[0][0] + pins[0][1]
        state = PIN_STATE.get(pincode[:3]) or PIN_STATE.get(pincode[:2])
    if not state:
        for s in STATES:
            if re.search(r"\b" + re.escape(s) + r"\b", body, re.I):
                state = s
                break
    return city, state, pincode


def property_type(text: str):
    t = text.lower()
    m = re.search(r"(description of (?:the )?(?:immovable )?propert|schedule|details of (?:the )?(?:immovable )?propert|property address|all that piece)", t)
    seg = t[m.start(): m.start() + 2000] if m else t[:4000]
    return clean_type(seg)


def parse_notice(text: str, bank: str, source: str, url: str, category: str, title: str | None = None) -> dict | None:
    if not text or len(text) < 80:
        return None
    reserve = amount_after(text, r"reserve\s*price")
    emd = amount_after(text, r"(earnest\s*money(?:\s*deposit)?|\bemd\b)")
    city, state, pincode = location(text)
    possession = None
    tl = text.lower()
    if "physical possession" in tl:
        possession = "Physical"
    elif "symbolic possession" in tl or "constructive possession" in tl:
        possession = "Symbolic"
    n_props = len(set(re.findall(r"\b(?:property|lot)\s*(?:no\.?\s*)?[-:]?\s*(\d{1,2}|i{1,3}|iv|v)\b", tl)))
    body = "\n".join(l for l in text.splitlines() if not OFFICE_LINE.search(l))
    m = re.search(r"(description of (?:the )?(?:immovable )?propert\w*|details of (?:the )?(?:immovable )?propert\w*|property address|all that (?:piece|part))\s*[:\-]?", body, re.I)
    desc = re.sub(r"\s+", " ", body[m.end(): m.end() + 400] if m else body[:400]).strip()
    rec = {
        "id": f"{source}:{re.sub(r'[^a-z0-9]+', '-', url.lower())[-80:]}",
        "bank": bank,
        "title": title or desc[:180],
        "property_type": property_type(text),
        "state": state, "city": city, "address": None, "pincode": pincode,
        "reserve_price": reserve, "emd": emd,
        "auction_date": auction_date(text), "emd_last_date": None,
        "possession": possession, "area": None, "auction_type": None, "contact": None,
        "url": url, "source": source, "category": category, "approx": True,
        "lots": n_props if n_props > 1 else None,
    }
    if not (rec["reserve_price"] or rec["auction_date"]):
        return None
    return rec
