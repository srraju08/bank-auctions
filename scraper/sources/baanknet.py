"""BAANKNET (baanknet.com) — all 12 public sector banks + IBBI.

BAANKNET is a JavaScript app that loads listings from its own JSON API.
Rather than hard-coding that API (which changes without notice), we:
  1. open the search page in a real headless browser,
  2. watch the network for JSON responses that contain property listings,
  3. page through them — first by replaying the API call with the page
     number increased, falling back to clicking "Next"/"Load more".

Run `python scraper/run.py --discover` once to dump the raw API responses
into scraper/debug/ so you can see the real field names.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.sync_api import sync_playwright

from normalize import find_listing_arrays, normalize

SOURCE = "baanknet"
BASE = "https://baanknet.com"
PAGE_KEYS = ["page", "pageNo", "pageNumber", "pageIndex", "currentPage", "start", "offset", "from", "skip"]
NEXT_BUTTON = re.compile(r"^\s*(next|load more|show more|›|»|>)\s*$", re.I)


def _set_page(url: str, body: str | None, key: str, value: int):
    p = urlparse(url)
    q = dict(parse_qsl(p.query))
    if key in q:
        q[key] = str(value)
        return urlunparse(p._replace(query=urlencode(q))), body
    if body:
        try:
            data = json.loads(body)
            if isinstance(data, dict) and key in data:
                data[key] = value
                return url, json.dumps(data)
        except ValueError:
            pass
    return None, None


def _page_key(url: str, body: str | None):
    q = dict(parse_qsl(urlparse(url).query))
    data = {}
    if body:
        try:
            data = json.loads(body) or {}
        except ValueError:
            data = {}
    for k in PAGE_KEYS:
        for src in (q, data if isinstance(data, dict) else {}):
            if k in src:
                try:
                    return k, int(src[k])
                except (TypeError, ValueError):
                    pass
    return None, None


def scrape(cfg: dict, debug_dir: Path | None = None, log=print) -> list[dict]:
    start_urls = cfg.get("start_urls", [BASE])
    max_pages = int(cfg.get("max_pages", 300))
    delay = float(cfg.get("delay_seconds", 1.5))
    records: dict[str, dict] = {}
    endpoints: list[dict] = []

    def ingest(payload, req_url, method, body):
        found = 0
        for path, arr in find_listing_arrays(payload):
            for raw in arr:
                rec = normalize(raw, SOURCE, BASE)
                if rec and rec["id"] not in records:
                    records[rec["id"]] = rec
                    found += 1
            if not any(e["url"] == req_url and e["body"] == body for e in endpoints):
                endpoints.append({"url": req_url, "method": method, "body": body, "path": path})
        return found

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
            locale="en-IN",
        )
        page = ctx.new_page()
        dump_n = [0]

        netlog = []

        def on_response(resp):
            ctype = resp.headers.get("content-type") or ""
            netlog.append(f"{resp.status} {resp.request.method} {resp.request.resource_type} {ctype[:40]} {resp.url[:160]}")
            if "json" not in ctype and resp.request.resource_type not in ("xhr", "fetch"):
                return
            try:
                payload = resp.json()
            except Exception:
                return
            req = resp.request
            n = ingest(payload, resp.url, req.method, req.post_data)
            if debug_dir is not None:
                dump_n[0] += 1
                debug_dir.mkdir(parents=True, exist_ok=True)
                (debug_dir / f"{dump_n[0]:03d}_{'LISTINGS_' if n else ''}{urlparse(resp.url).path.strip('/').replace('/', '_')[:60]}.json").write_text(
                    json.dumps({"url": resp.url, "method": req.method, "body": req.post_data, "payload": payload}, indent=1, ensure_ascii=False)[:2_000_000]
                )
            if n:
                log(f"  +{n} listings from {resp.url[:100]}")

        page.on("response", on_response)

        for url in start_urls:
            log(f"Opening {url}")
            try:
                page.goto(url, wait_until="networkidle", timeout=90_000)
            except Exception as e:
                log(f"  load warning: {e}")
            time.sleep(delay)
            time.sleep(8)  # SPA needs time to fetch listings
            for _ in range(4):  # trigger lazy loading
                page.mouse.wheel(0, 4000)
                time.sleep(delay)
            log(f"  landed on {page.url} | title: {page.title()!r} | {len(records)} listings so far")
            if debug_dir is not None:
                debug_dir.mkdir(parents=True, exist_ok=True)
                slug = re.sub(r"[^a-z0-9]+", "_", url.lower())[-40:]
                page.screenshot(path=str(debug_dir / f"page_{slug}.png"), full_page=True)
                (debug_dir / f"page_{slug}.html").write_text(page.content())
                links = page.eval_on_selector_all("a[href]", "els => [...new Set(els.map(e => e.href))]")
                (debug_dir / f"links_{slug}.txt").write_text("\n".join(links))
                log("  body text: " + page.inner_text("body")[:400].replace("\n", " | "))

        # 1) API replay — fastest and most complete
        for ep in list(endpoints):
            key, current = _page_key(ep["url"], ep["body"])
            if not key:
                continue
            log(f"Paging API via '{key}' : {ep['url'][:90]}")
            step = 1 if key not in ("start", "offset", "from", "skip") else None
            if step is None:
                step = max(1, len(records))  # offset-style: jump by page size seen
            empty_runs = 0
            for i in range(1, max_pages):
                nxt = current + i * step
                url, body = _set_page(ep["url"], ep["body"], key, nxt)
                if not url:
                    break
                try:
                    if ep["method"] == "POST":
                        r = ctx.request.post(url, data=body, headers={"content-type": "application/json"}, timeout=60_000)
                    else:
                        r = ctx.request.get(url, timeout=60_000)
                    new = ingest(r.json(), url, ep["method"], body)
                except Exception as e:
                    log(f"  stop at page {nxt}: {e}")
                    break
                log(f"  page {nxt}: +{new} (total {len(records)})")
                empty_runs = empty_runs + 1 if new == 0 else 0
                if empty_runs >= 2:
                    break
                time.sleep(delay)
            break  # one good endpoint is enough

        # 2) UI fallback — click Next / Load more
        if not any(_page_key(e["url"], e["body"])[0] for e in endpoints):
            log("No pageable API found; clicking through the UI instead")
            for i in range(max_pages):
                before = len(records)
                btn = page.get_by_role("button", name=NEXT_BUTTON).or_(page.get_by_role("link", name=NEXT_BUTTON)).first
                try:
                    if not btn.is_visible() or not btn.is_enabled():
                        break
                    btn.click()
                    page.wait_for_load_state("networkidle", timeout=30_000)
                except Exception:
                    break
                time.sleep(delay)
                if len(records) == before:
                    break
                log(f"  ui page {i + 2}: total {len(records)}")

        browser.close()

    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "network_log.txt").write_text("\n".join(netlog))
        log(f"  network: {len(netlog)} responses; api-like:")
        for line in [l for l in netlog if " xhr " in l or " fetch " in l][:40]:
            log("    " + line)
    log(f"BAANKNET: {len(records)} listings")
    return list(records.values())
