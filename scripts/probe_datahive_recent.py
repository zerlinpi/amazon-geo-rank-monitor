#!/usr/bin/env python3
import requests, pandas as pd, os, re, json, sys
from pathlib import Path

BASE="https://huggingface.co/datasets/datahiveai/Amazon-Reviews-Dataset/resolve/main"
out=Path("/tmp/hf_amazon"); out.mkdir(exist_ok=True)
def dl(name):
    p=out/name
    if p.exists(): return p
    u=f"{BASE}/{name}?download=true"
    print("download",u,flush=True)
    with requests.get(u,stream=True,timeout=(30,600)) as r:
        r.raise_for_status()
        with open(p,"wb") as f:
            for ch in r.iter_content(8*1024*1024):
                if ch: f.write(ch)
    print(name,"bytes",p.stat().st_size,flush=True)
    return p

pp=dl("products.csv"); rp=dl("reviews.csv")
products=pd.read_csv(pp)
print("PRODUCT COLS",products.columns.tolist(),flush=True)
print("PRODUCT ROWS",len(products),flush=True)
pat=re.compile(r"walking\s*pad|walkingpad|under[-\s]?desk\s+treadmill|desk\s+treadmill|walking\s+treadmill|compact\s+treadmill|portable\s+treadmill|urevo|deerrun|sperax|egofit|goyouth|goplus|merach|kingsmith|toputure|wellfit|maksone|vitalwalk",re.I)
blob=products.astype(str).agg(" ".join,axis=1)
matches=products[blob.str.contains(pat,na=False)]
print("MATCHED PRODUCTS",len(matches),flush=True)
print(matches.head(50).to_json(orient="records",force_ascii=False),flush=True)
print("REVIEWS HEADER",pd.read_csv(rp,nrows=3).columns.tolist(),flush=True)
print(pd.read_csv(rp,nrows=3).to_json(orient="records",force_ascii=False),flush=True)

review_cols=pd.read_csv(rp,nrows=0).columns.tolist()
join_candidates=[c for c in review_cols if c.lower() in ("asin","product_asin","parent_asin","product_id","url","product_url")]
date_candidates=[c for c in review_cols if "date" in c.lower() or "time" in c.lower()]
print("JOIN CANDIDATES",join_candidates,"DATE CANDIDATES",date_candidates,flush=True)
match_ids=set()
for c in products.columns:
    if c.lower() in ("asin","product_asin","parent_asin","product_id","url"):
        match_ids.update(matches[c].dropna().astype(str).tolist())
print("MATCH IDS",len(match_ids),flush=True)

total=recent=matched=matched_recent=0
min_date=max_date=None
recent_examples=[]
cutoff=pd.Timestamp("2024-09-28")
for chunk in pd.read_csv(rp,chunksize=50000):
    total+=len(chunk)
    datecol=date_candidates[0] if date_candidates else None
    if datecol:
        dates=pd.to_datetime(chunk[datecol],errors="coerce")
        if dates.notna().any():
            mn=dates.min(); mx=dates.max()
            min_date=mn if min_date is None or mn<min_date else min_date
            max_date=mx if max_date is None or mx>max_date else max_date
        recmask=dates>=cutoff
        recent+=int(recmask.sum())
    else:
        recmask=pd.Series(False,index=chunk.index)
    msk=pd.Series(False,index=chunk.index)
    for c in join_candidates:
        vals=chunk[c].astype(str)
        msk |= vals.isin(match_ids)
    matched+=int(msk.sum())
    matched_recent+=int((msk & recmask).sum())
    if len(recent_examples)<20:
        ex=chunk[msk & recmask].head(20-len(recent_examples))
        recent_examples.extend(ex.to_dict("records"))
print(json.dumps({
 "total_reviews":total,"recent_reviews":recent,"matched_products":len(matches),
 "matched_reviews":matched,"matched_recent_reviews":matched_recent,
 "min_date":str(min_date),"max_date":str(max_date),
 "review_cols":review_cols,"join_candidates":join_candidates,
 "examples":recent_examples
},ensure_ascii=False,default=str),flush=True)
