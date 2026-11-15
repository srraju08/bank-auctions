"""Run all sources, merge with yesterday's data, write docs/data/*.json.

  python scraper/run.py              # normal daily run
  python scraper/run.py --discover   # also dump raw API JSON to scraper/debug/
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from sources import baanknet, ibbi, notices  # noqa: E402

ROOT = HERE.parent
DATA = ROOT / "docs" / "data"
SOURCES = {"baanknet": baanknet.scrape, "ibbi": ibbi.scrape, "notices": notices.scrape}
IST = timezone(timedelta(hours=5, minutes=30))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true", help="dump raw JSON responses to scraper/debug/")
    args = ap.parse_args()

    cfg = json.loads((HERE / "config.json").read_text())
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")

    old_path = DATA / "listings.json"
    old = {}
    old_meta = {}
    if old_path.exists():
        old = {r["id"]: r for r in json.loads(old_path.read_text())}
        if (DATA / "meta.json").exists():
            old_meta = json.loads((DATA / "meta.json").read_text())
    if old_meta.get("sample"):
        old = {}  # never mix sample rows into real data

    fresh, status = {}, {}
    for name, fn in SOURCES.items():
        if not cfg.get("sources", {}).get(name, {}).get("enabled", True):
            continue
        try:
            out = fn(cfg["sources"][name], HERE / "debug" / name if args.discover else None)
            rows, st = out if isinstance(out, tuple) else (out, {"ok": True, "count": len(out)})
            if name == "baanknet" and not rows:
                st = {"ok": False, "error": "0 listings - site is probably blocking this server"}
            if name == "notices":
                status.update(st)  # one entry per lender
            else:
                status[name] = st
            for r in rows:
                r.setdefault("category", "PSU bank (BAANKNET)")
                fresh[r["id"]] = r
        except Exception as e:  # one broken source must not kill the run
            status[name] = {"ok": False, "error": str(e)[:300]}
            print(f"!! {name} failed: {e}")

    if not fresh and old:
        print("!! Nothing scraped — keeping previous data untouched.")
        meta = dict(old_meta, last_attempt=now.isoformat(), sources=status)
        (DATA / "meta.json").write_text(json.dumps(meta, indent=1))
        sys.exit(1)

    keep_days = int(cfg.get("keep_days_after_auction", 3))
    cutoff = (now - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    merged = {}
    for rid, r in fresh.items():
        r["first_seen"] = old.get(rid, {}).get("first_seen", today)
        r["last_seen"] = today
        merged[rid] = r
    for rid, r in old.items():  # listing vanished from source but auction not over yet
        if rid not in merged and (r.get("auction_date") or "9999") >= cutoff and r.get("last_seen", "") >= (now - timedelta(days=7)).strftime("%Y-%m-%d"):
            merged[rid] = r
    rows = [r for r in merged.values() if (r.get("auction_date") or "9999") >= cutoff]
    rows.sort(key=lambda r: r.get("auction_date") or "9999")

    DATA.mkdir(parents=True, exist_ok=True)
    old_path.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
    meta = {
        "updated": now.isoformat(),
        "last_attempt": now.isoformat(),
        "total": len(rows),
        "new_today": sum(1 for r in rows if r["first_seen"] == today),
        "sources": status,
        "sample": False,
    }
    (DATA / "meta.json").write_text(json.dumps(meta, indent=1))
    print(f"Wrote {len(rows)} listings ({meta['new_today']} new)")


if __name__ == "__main__":
    main()
