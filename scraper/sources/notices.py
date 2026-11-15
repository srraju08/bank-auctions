"""Generic adapter for lenders that publish sale notices as web pages / PDFs.

Each lender is just an entry in config.json -> sources.notices.sites:
  {
    "key": "axis", "bank": "Axis Bank", "category": "Private bank",
    "index_urls": ["https://www.axisbank.com/auction-notices"],
    "pdf_pattern": "auction-notices/.+\\.pdf",     # which links are notices
    "cards": false                                   # also read listings shown as HTML cards
  }
Adding a new bank / NBFC / ARC = adding one entry. No code.

PDFs already parsed are cached in scraper/cache/notices.json so each daily
run only downloads new notices.
"""
from __future__ import annotations

import io
import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from textparse import parse_notice

CACHE = Path(__file__).resolve().parent.parent / "cache" / "notices.json"
CARD_JS = """() => {
  const out = [];
  for (const el of document.querySelectorAll('div,li,tr,article,section')) {
    const t = (el.innerText || '').trim();
    if (t.length < 60 || t.length > 2500) continue;
    if (!/(₹|Rs\\.?\\s?\\d|reserve)/i.test(t)) continue;
    // keep only the smallest element that contains a price
    if ([...el.children].some(c => /(₹|Rs\\.?\\s?\\d|reserve)/i.test(c.innerText || '') && (c.innerText||'').length >= 60)) continue;
    const a = el.querySelector('a[href]');
    out.push({text: t, href: a ? a.href : null});
  }
  return out;
}"""


def _pdf_text(data: bytes) -> str:
    import pdfplumber
    parts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:6]:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _title_from_url(url: str) -> str:
    name = re.sub(r"\?.*$", "", url).rsplit("/", 1)[-1]
    name = re.sub(r"\.pdf$", "", name, flags=re.I)
    name = re.sub(r"[-_%20]+", " ", name)
    return name.strip().title()[:160]


def scrape(cfg: dict, debug_dir: Path | None = None, log=print) -> tuple[list[dict], dict]:
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    rows: list[dict] = []
    status: dict[str, dict] = {}
    max_new = int(cfg.get("max_new_pdfs_per_site", 60))
    delay = float(cfg.get("delay_seconds", 1.0))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
            locale="en-IN",
        )
        for site in cfg.get("sites", []):
            if not site.get("enabled", True):
                continue
            key, bank, cat = site["key"], site["bank"], site.get("category", "Private bank")
            st = {"ok": False, "reached": [], "blocked": [], "pdf_links": 0, "parsed": 0, "count": 0}
            status[key] = st
            pat = re.compile(site.get("pdf_pattern", r"\.pdf"), re.I)
            links: set[str] = set()
            page = ctx.new_page()
            for url in site["index_urls"]:
                try:
                    resp = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=20_000)
                    except Exception:
                        pass
                    code = resp.status if resp else 0
                    title = page.title()
                    if code >= 400 or re.search(r"forbidden|access denied|not found|attention required", title, re.I):
                        st["blocked"].append(f"{code} {title[:40]} {url}")
                        log(f"[{key}] BLOCKED {code} '{title}' {url}")
                        continue
                    st["reached"].append(url)
                    # some lists load more on scroll
                    for _ in range(3):
                        page.mouse.wheel(0, 5000)
                        time.sleep(0.6)
                    hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
                    found = {h for h in hrefs if pat.search(h)}
                    links |= found
                    log(f"[{key}] {url} -> {len(found)} notice links")
                    if site.get("cards"):
                        for c in page.evaluate(CARD_JS):
                            rec = parse_notice(c["text"], bank, key, c["href"] or url, cat, title=c["text"].split("\n")[0][:160])
                            if rec:
                                rec["id"] = f"{key}:card:{abs(hash(c['text'][:300])) % 10**10}"
                                rows.append(rec)
                    if debug_dir is not None:
                        debug_dir.mkdir(parents=True, exist_ok=True)
                        slug = re.sub(r"[^a-z0-9]+", "_", url.lower())[-50:]
                        page.screenshot(path=str(debug_dir / f"{key}_{slug}.png"), full_page=True)
                        (debug_dir / f"{key}_{slug}_links.txt").write_text("\n".join(sorted(set(hrefs))))
                except Exception as e:
                    st["blocked"].append(f"error {str(e)[:80]} {url}")
                    log(f"[{key}] ERROR {url}: {e}")
            page.close()
            st["pdf_links"] = len(links)

            new = 0
            def recency(u):  # newest notices first (dates like 03-11-26 in file names)
                m = re.search(r"(\d{2})[-_](\d{2})[-_](\d{2,4})(?:\D*$|\.pdf)", u)
                if not m:
                    return "0"
                y = m.group(3)[-2:]
                return f"{y}{m.group(2)}{m.group(1)}"
            for link in sorted(links, key=recency, reverse=True):
                if link in cache:
                    rec = cache[link]
                else:
                    if new >= max_new:
                        continue
                    new += 1
                    try:
                        r = ctx.request.get(link, timeout=60_000)
                        if not r.ok:
                            continue
                        t = _title_from_url(link)
                        good = len(t) >= 20 and sum(ch.isdigit() for ch in t) < len(t) * 0.15
                        rec = parse_notice(_pdf_text(r.body()), bank, key, link, cat, title=t if good else None)
                    except Exception as e:
                        log(f"[{key}] pdf fail {link[:90]}: {e}")
                        rec = None
                    cache[link] = rec  # cache failures too, so we don't retry daily
                    time.sleep(delay)
                if rec:
                    rows.append(rec)
                    st["parsed"] += 1
            st["count"] = sum(1 for r in rows if r["source"] == key)
            st["ok"] = bool(st["reached"])
            log(f"[{key}] reached={len(st['reached'])} blocked={len(st['blocked'])} pdfs={len(links)} new={new} listings={st['count']}")
        browser.close()

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False))
    return rows, status
