# Bank Auction Finder (India)

Each day a scraper collects bank auction property listings from **BAANKNET**
(all 12 public sector banks + IBBI). The listings are published as a
filterable website on GitHub Pages. Hosting is free, and you don't need a server.

```
GitHub Actions (daily 06:47 IST)            GitHub Pages
  scraper/run.py  ──writes──►  docs/data/listings.json  ──►  docs/index.html
  (headless Chrome)                                         (filters, saved prefs)
```

## Setup (about 10 minutes, can be done from a phone browser)

1. Create a GitHub account if you don't have one. Then create a **new public repository**,
   for example `bank-auctions`.
2. Upload every file and folder from this zip (**Add file → Upload files**). Drag the
   whole unzipped folder in, including the hidden `.github` folder.
   - If your upload skips `.github`, create the file
     `.github/workflows/scrape.yml` by hand and paste in its contents.
3. Go to **Settings → Pages**. Under *Source*, choose **Deploy from a branch**.
   Pick branch `main`, folder **`/docs`**, then Save.
   Your site will be at `https://<your-username>.github.io/bank-auctions/`.
4. Go to **Settings → Actions → General → Workflow permissions** and choose
   **Read and write permissions**, then Save. The bot needs this to commit fresh data.
5. Go to **Actions → Scrape bank auctions → Run workflow**. Tick **discover**
   for the first run.

Until the first successful run, the site shows **made-up sample listings**
and a yellow banner says so.

## The first run: check it, don't assume

BAANKNET is a JavaScript app with no published API, so the scraper finds
listings by watching the page's own network calls. That is robust, but it is
untested against the live site, which isn't reachable from where this was built.
After the first run:

- **Listings appear on your site** → done.
- **0 listings / red ✗ in Actions** → open the run, scroll down to
  **Artifacts → raw-responses**, and download it. Files whose names start with
  `LISTINGS_` are the API responses that held properties. If none have that name,
  the start URL is wrong or the field names differ:
  - Open baanknet.com on a computer, go to the property search page, and copy its URL
    into `scraper/config.json → start_urls`.
  - If the raw JSON uses field names the scraper doesn't recognise (for example
    `rsrvPrc` for reserve price), add them to `FIELD_CANDIDATES` in
    `scraper/normalize.py`.

If a refresh fails later, the site keeps showing the last good data and shows
a banner. It never wipes your data because of one bad run.

## Using the site

- Filter by state → city, property type, bank, possession, price (₹ lakh),
  and how soon the auction is.
- **Save as my preferences** keeps your filters in this browser.
- **Copy link to this search** creates a link with your filters built in. Bookmark it
  on your phone.
- Tags: **New** = first seen in the last 3 days, **Nd left** = auction within a week.

## What it does NOT cover (yet)

- **Private banks** (HDFC, ICICI, Axis, Kotak…) and ARCs/NBFCs publish
  mostly PDF sale notices on their own sites. Each one needs its own adapter in
  `scraper/sources/`. Add one at a time, and only for banks active in your areas.
- **DRT auctions** and state-government auctions.

## Running locally (optional)

```bash
pip install -r requirements.txt
python -m playwright install chromium
python scraper/run.py --discover
python -m http.server -d docs 8000   # open http://localhost:8000
```

## Before you bid

The scraped data is a lead, not a sale notice. Always read the bank's official
sale notice and confirm the reserve price, EMD and dates there. Also check title,
dues and possession status (*symbolic* possession means the bank has not yet
taken physical control).
