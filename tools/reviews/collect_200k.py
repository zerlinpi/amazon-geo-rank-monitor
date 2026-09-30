#!/usr/bin/env python3
"""
Collect up to 200,000 recent Walmart walking-pad / treadmill reviews via Apify.

Environment:
  APIFY_TOKEN   required
Optional:
  TARGET_ROWS   default 200000
  CUTOFF_DATE   default 2024-09-29
  OUT_DIR       default out

The script:
- starts from Walmart search/category URLs
- uses the Apify Walmart Reviews Scraper
- requests newest-first reviews
- filters by cutoff date
- deduplicates by reviewId, falling back to a content key
- preserves source platform, product URL, product ID, review URL/date/text/rating/author
- writes CSV + XLSX + progress JSON
"""
import csv, hashlib, json, os, sys, time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
import pandas as pd

APIFY_TOKEN = os.environ.get("APIFY_TOKEN")
TARGET_ROWS = int(os.environ.get("TARGET_ROWS", "200000"))
CUTOFF_DATE = os.environ.get("CUTOFF_DATE", "2024-09-29")
OUT_DIR = Path(os.environ.get("OUT_DIR", "out"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

if not APIFY_TOKEN:
    raise SystemExit("APIFY_TOKEN is required")

# Actor supports Walmart search/category/product URLs, date filtering, newest-first,
# and structured review output.
ACTOR_ID = os.environ.get("APIFY_ACTOR_ID", "e-commerce~walmart-reviews-scraper")

START_URLS = [
    "https://www.walmart.com/search?q=walking+pad",
    "https://www.walmart.com/search?q=under+desk+treadmill",
    "https://www.walmart.com/search?q=folding+treadmill",
    "https://www.walmart.com/search?q=incline+treadmill",
    "https://www.walmart.com/search?q=portable+treadmill",
    "https://www.walmart.com/search?q=walking+treadmill",
]

def apify(path, method="GET", payload=None, params=None):
    url = f"https://api.apify.com/v2/{path}"
    params = dict(params or {})
    params["token"] = APIFY_TOKEN
    r = requests.request(method, url, params=params, json=payload, timeout=120)
    r.raise_for_status()
    return r.json()

def parse_date(v):
    if not v:
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s[:len(fmt.replace('%',''))], fmt).date()
        except Exception:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z","+00:00")).date()
    except Exception:
        return None

def norm(row):
    review_id = row.get("reviewId") or row.get("feedbackId") or row.get("id")
    product_id = row.get("productId") or row.get("itemId") or row.get("usItemId")
    product_url = row.get("productUrl") or row.get("itemUrl") or row.get("url")
    product_name = row.get("productTitle") or row.get("itemName") or row.get("productName")
    review_date = row.get("submissionTime") or row.get("reviewSubmissionTime") or row.get("date") or row.get("reviewDate")
    review_text = row.get("text") or row.get("feedbackText") or row.get("reviewText") or ""
    review_title = row.get("title") or row.get("feedbackTitle") or row.get("reviewTitle") or ""
    author = row.get("authorName") or row.get("reviewerNickname") or row.get("author") or ""
    rating = row.get("rating") or row.get("starRating")
    verified = row.get("verifiedPurchase")
    if verified is None:
        verified = row.get("verifiedBuyer")
    review_url = row.get("reviewUrl") or product_url
    syndicated_from = row.get("syndicatedFrom") or row.get("externalSource") or ""
    if not review_id:
        raw = "|".join(map(str, [product_id, review_date, author, review_title, review_text]))
        review_id = hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()
    return {
        "source_platform": "Walmart",
        "source_origin": syndicated_from or "Walmart",
        "product_id": product_id,
        "product_name": product_name,
        "product_url": product_url,
        "review_id": str(review_id),
        "review_date": str(review_date or ""),
        "rating": rating,
        "review_title": review_title,
        "review_text": review_text,
        "author": author,
        "verified_purchase": verified,
        "review_url": review_url,
        "scraped_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }

def main():
    payload = {
        "startUrls": [{"url": u} for u in START_URLS],
        "maxProductsPerStartUrl": 500,
        "maxReviewsPerProduct": 2000,
        "reviewsSortType": "submission-desc",
        "scrapeUntilDate": CUTOFF_DATE,
    }
    run = apify(f"acts/{ACTOR_ID}/runs", "POST", payload=payload)
    run_id = run["data"]["id"]
    print("run_id", run_id, flush=True)

    while True:
        st = apify(f"actor-runs/{run_id}")
        status = st["data"]["status"]
        print("status", status, flush=True)
        if status in {"SUCCEEDED","FAILED","ABORTED","TIMED-OUT"}:
            break
        time.sleep(15)
    if status != "SUCCEEDED":
        raise SystemExit(f"Apify run ended with {status}")

    dataset_id = st["data"]["defaultDatasetId"]
    offset = 0
    limit = 1000
    rows = []
    seen = set()
    cutoff = datetime.strptime(CUTOFF_DATE, "%Y-%m-%d").date()

    while len(rows) < TARGET_ROWS:
        data = apify(f"datasets/{dataset_id}/items", params={"offset":offset,"limit":limit,"clean":"true"})
        items = data.get("data", {}).get("items") if isinstance(data, dict) else None
        if items is None:
            # Apify dataset endpoint may return the list body depending on API wrapper/version.
            items = data if isinstance(data, list) else []
        if not items:
            break
        for item in items:
            r = norm(item)
            d = parse_date(r["review_date"])
            if d and d < cutoff:
                continue
            if not r["review_text"].strip():
                continue
            key = r["review_id"]
            if key in seen:
                continue
            seen.add(key)
            rows.append(r)
            if len(rows) >= TARGET_ROWS:
                break
        offset += len(items)
        print("unique_rows", len(rows), "offset", offset, flush=True)
        if len(items) < limit:
            break

    df = pd.DataFrame(rows[:TARGET_ROWS])
    csv_path = OUT_DIR / "walking_pad_reviews_200k.csv"
    xlsx_path = OUT_DIR / "walking_pad_reviews_200k.xlsx"
    progress_path = OUT_DIR / "progress.json"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    df.to_excel(xlsx_path, index=False)
    progress_path.write_text(json.dumps({
        "rows": len(df),
        "target": TARGET_ROWS,
        "cutoff_date": CUTOFF_DATE,
        "dataset_id": dataset_id,
        "run_id": run_id,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds")+"Z",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(csv_path)
    print(xlsx_path)
    print(progress_path)

if __name__ == "__main__":
    main()
