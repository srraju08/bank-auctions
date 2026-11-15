"""IBBI liquidation auction notices (ibbi.gov.in) — insolvency (NCLT) sales.

The list page is an HTML table, newest first. Columns are matched by header
text so small layout changes don't break it.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from normalize import clean_type, to_iso_date, to_number
from textparse import location

BASE = "https://ibbi.gov.in/liquidation-auction-notices/lists"


def _col(headers, *words):
    for i, h in enumerate(headers):
        if all(w in h for w in words):
            return i
    return None


def scrape(cfg: dict, debug_dir: Path | None = None, log=print) -> tuple[list[dict], dict]:
    pages = int(cfg.get("pages", 5))
    rows, st = [], {"ok": False, "reached": [], "blocked": [], "count": 0}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(locale="en-IN")
        for p in range(pages):
            url = f"{BASE}?page={p}"
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            except Exception as e:
                st["blocked"].append(f"error {str(e)[:80]}")
                log(f"[ibbi] ERROR {url}: {e}")
                break
            title = page.title()
            if not resp or resp.status >= 400 or "forbidden" in title.lower():
                st["blocked"].append(f"{resp.status if resp else 0} {title[:40]}")
                log(f"[ibbi] BLOCKED {url} '{title}'")
                break
            st["reached"].append(url)
            if debug_dir is not None and p == 0:
                debug_dir.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(debug_dir / "ibbi_page0.png"), full_page=True)
            table = page.evaluate("""() => {
              const t = [...document.querySelectorAll('table')].sort((a,b)=>b.rows.length-a.rows.length)[0];
              if (!t) return null;
              const head = [...t.querySelectorAll('thead th, tr:first-child th')].map(th => th.innerText.trim().toLowerCase());
              const body = [...t.querySelectorAll('tbody tr')].map(tr => [...tr.cells].map(td => ({
                  text: td.innerText.trim(), href: (td.querySelector('a[href]')||{}).href || null })));
              return {head, body};
            }""")
            if not table or not table["body"]:
                log(f"[ibbi] no table on {url}")
                break
            h = table["head"]
            c_debtor = _col(h, "corporate") or _col(h, "debtor")
            c_auction = next((i for i, x in enumerate(h) if "auction" in x and "date" in x and "notice" not in x), None)
            c_reserve = _col(h, "reserve")
            c_desc = _col(h, "description") or _col(h, "assets")
            c_last = _col(h, "last", "date")
            for cells in table["body"]:
                def g(i):
                    return cells[i]["text"] if i is not None and i < len(cells) else None
                desc = g(c_desc) or ""
                debtor = g(c_debtor) or ""
                city, state, pin = location(desc)
                link = next((c["href"] for c in cells if c["href"] and ".pdf" in c["href"].lower()), None) or \
                       next((c["href"] for c in cells if c["href"]), BASE)
                rec = {
                    "id": f"ibbi:{re.sub(r'[^a-z0-9]+', '-', (debtor + (g(c_auction) or '')).lower())[:80]}",
                    "bank": "IBBI Liquidation", "title": f"{debtor} — {desc}"[:220],
                    "property_type": clean_type(desc), "state": state, "city": city, "address": None, "pincode": pin,
                    "reserve_price": to_number(g(c_reserve)), "emd": None,
                    "auction_date": to_iso_date(g(c_auction)), "emd_last_date": to_iso_date(g(c_last)),
                    "possession": None, "area": None, "auction_type": "IBC liquidation", "contact": None,
                    "url": link, "source": "ibbi", "category": "IBBI liquidation", "approx": True,
                }
                if rec["reserve_price"] or rec["auction_date"]:
                    rows.append(rec)
            log(f"[ibbi] page {p}: total {len(rows)}")
            time.sleep(1)
        browser.close()
    st["ok"] = bool(st["reached"])
    st["count"] = len(rows)
    return rows, st
