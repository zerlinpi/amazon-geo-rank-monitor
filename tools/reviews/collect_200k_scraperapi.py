#!/usr/bin/env python3
import csv, os, time, json, hashlib
from datetime import datetime
from pathlib import Path
import requests
import pandas as pd

API_KEY = os.environ["SCRAPERAPI_KEY"]
TARGET = int(os.environ.get("TARGET_ROWS", "200000"))
CUTOFF = datetime.strptime(os.environ.get("CUTOFF_DATE","2024-09-29"), "%Y-%m-%d").date()
OUT = Path(os.environ.get("OUT_DIR","out")); OUT.mkdir(parents=True, exist_ok=True)

SEARCH_TERMS = [
    "walking pad","under desk treadmill","portable treadmill",
    "incline treadmill","folding treadmill","walking treadmill"
]

BASE = "https://api.scraperapi.com/structured/walmart"

def api(endpoint, **params):
    p={"api_key":API_KEY, **params}
    r=requests.get(f"{BASE}/{endpoint}", params=p, timeout=120)
    r.raise_for_status()
    return r.json()

def dt(v):
    if not v: return None
    for f in ("%m/%d/%Y","%Y-%m-%d","%b %d, %Y"):
        try: return datetime.strptime(str(v),f).date()
        except: pass
    return None

def review_key(pid, r):
    rid=r.get("review_id") or r.get("id")
    if rid: return f"{pid}:{rid}"
    raw="|".join(str(r.get(k,"")) for k in ("date_published","author","title","text"))
    return f"{pid}:{hashlib.sha1(raw.encode()).hexdigest()}"

def discover_products():
    seen={}
    for term in SEARCH_TERMS:
        for page in range(1, 21):
            try:
                d=api("search", query=term, page=page)
            except Exception:
                break
            items=d.get("items") or d.get("results") or d.get("products") or []
            if not items: break
            for x in items:
                pid=str(x.get("product_id") or x.get("id") or x.get("us_item_id") or "")
                name=x.get("name") or x.get("title") or ""
                url=x.get("url") or x.get("product_url") or ""
                if pid:
                    seen[pid]={"product_id":pid,"product_name":name,"product_url":url,"query":term}
    return list(seen.values())

def main():
    products=discover_products()
    print("discovered",len(products),flush=True)
    rows=[]; seen=set()
    for i,p in enumerate(products,1):
        if len(rows)>=TARGET: break
        pid=p["product_id"]
        for page in range(1,1000):
            try:
                d=api("review", product_id=pid, page=page, sort="submission-desc", output_format="json")
            except Exception as e:
                print("ERR",pid,page,e,flush=True); break
            reviews=d.get("reviews") or []
            if not reviews: break
            stop=False
            for r in reviews:
                rd=dt(r.get("date_published") or r.get("review_date") or r.get("date"))
                if rd and rd < CUTOFF:
                    stop=True; continue
                txt=(r.get("text") or r.get("review_text") or "").strip()
                if not txt: continue
                k=review_key(pid,r)
                if k in seen: continue
                seen.add(k)
                rows.append({
                    "source_platform":"Walmart",
                    "product_id":pid,
                    "product_name":d.get("product_name") or p["product_name"],
                    "product_url":d.get("product_url") or p["product_url"],
                    "review_id":r.get("review_id") or r.get("id"),
                    "review_date":str(rd or r.get("date_published") or r.get("review_date") or ""),
                    "rating":r.get("rating"),
                    "review_title":r.get("title"),
                    "review_text":txt,
                    "author":r.get("author") or r.get("reviewer_name"),
                    "verified_purchase":"Verified Purchase" in (r.get("badges") or []) or r.get("verified_purchase"),
                    "positive_feedback":r.get("positive_feedback"),
                    "negative_feedback":r.get("negative_feedback"),
                    "review_page":f"https://www.walmart.com/reviews/product/{pid}?sort=submission-desc&page={page}",
                    "source_api":"ScraperAPI Walmart Reviews",
                })
                if len(rows)>=TARGET: break
            print(i,pid,page,len(rows),flush=True)
            if len(rows)>=TARGET or stop: break

    df=pd.DataFrame(rows[:TARGET])
    df.to_csv(OUT/"walking_pad_reviews_200k.csv",index=False,encoding="utf-8-sig")
    df.to_excel(OUT/"walking_pad_reviews_200k.xlsx",index=False)
    (OUT/"progress.json").write_text(json.dumps({
        "rows":len(df),"target":TARGET,"products_scanned":len(products),
        "cutoff":str(CUTOFF),"generated_at":datetime.utcnow().isoformat()+"Z"
    },indent=2),encoding="utf-8")
    print("DONE",len(df))

if __name__=="__main__":
    main()
