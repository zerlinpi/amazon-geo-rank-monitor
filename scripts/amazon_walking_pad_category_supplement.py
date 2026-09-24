#!/usr/bin/env python3
import csv,json,os,re,hashlib,gzip,io
from datetime import datetime,timezone
from pathlib import Path
import requests

CAT=os.environ["AMAZON_CATEGORY"]
OUT=Path(os.getenv("OUTDIR","amazon_supp_output"));OUT.mkdir(parents=True,exist_ok=True)
MAX_KEEP=int(os.getenv("MAX_KEEP","50000"))
BASE="https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw"
META=f"{BASE}/meta_categories/meta_{CAT}.jsonl.gz"
REV=f"{BASE}/review_categories/{CAT}.jsonl.gz"
KEY=["walking pad","walkingpad","under desk treadmill","under-desk treadmill","desk treadmill","walking treadmill","portable treadmill","compact treadmill","foldable treadmill","folding treadmill","mini treadmill","2 in 1 treadmill","2-in-1 treadmill","home office treadmill","treadmill for office","treadmill under desk"]
BR=["walkingpad","kingsmith","urevo","deerrun","sperax","egofit","goyouth","goplus","merach","lifespan","sunny health","toputure","maksone","wellfit","axefit","motiongrey","freepi","vitalwalk"]
def norm(s):return re.sub(r"\s+"," ",str(s or "").strip().lower())
def txt(v):
 if v is None:return ""
 if isinstance(v,(list,tuple)):return " ".join(map(str,v))
 if isinstance(v,dict):return json.dumps(v,ensure_ascii=False)
 return str(v)
def match(r):
 b=norm(" ".join([txt(r.get("title")),txt(r.get("description")),txt(r.get("features")),txt(r.get("categories")),txt(r.get("store"))]))
 return any(k in b for k in KEY) or (any(x in b for x in BR) and "treadmill" in b and any(x in b for x in ["walking","under desk","foldable","folding","compact","portable","2 in 1","2-in-1","mini"]))
def stream(url):
 with requests.get(url,stream=True,timeout=(30,900),headers={"User-Agent":"walking-pad-voc-amazon-supp/1.0"}) as r:
  r.raise_for_status();r.raw.decode_content=False
  with gzip.GzipFile(fileobj=r.raw,mode="rb") as gz:
   t=io.TextIOWrapper(gz,encoding="utf-8",errors="replace")
   for line in t:
    try:yield json.loads(line)
    except:continue
def date(ts):
 try:
  x=float(ts);x=x/1000 if x>1e12 else x
  return datetime.fromtimestamp(x,tz=timezone.utc).date().isoformat()
 except:return ""
products={};ms=0
for r in stream(META):
 ms+=1
 if match(r):
  p=str(r.get("parent_asin") or "")
  if p:products[p]={"title":txt(r.get("title")),"brand":txt(r.get("store"))}
 if ms%500000==0:print(f"{CAT} meta={ms:,} products={len(products):,}",flush=True)
print(f"{CAT} metadata complete scanned={ms:,} products={len(products):,}",flush=True)
rows=[];seen=set();rs=0;raw=0
for r in stream(REV):
 rs+=1;p=str(r.get("parent_asin") or "")
 if p not in products:continue
 body=txt(r.get("text")).strip()
 if len(body)<8:continue
 raw+=1
 h=hashlib.sha256((norm(body)+"|"+p).encode()).hexdigest()
 if h in seen:continue
 seen.add(h);pr=products[p]
 rows.append({"platform":f"Amazon Reviews 2023 - {CAT}","source_type":"historical product review","source_url":f"https://www.amazon.com/dp/{p}",
 "date":date(r.get("timestamp")),"rating_or_score":r.get("rating"),"verified_purchase":r.get("verified_purchase"),"helpful_vote":r.get("helpful_vote"),
 "brand":pr["brand"],"model":pr["title"],"asin":txt(r.get("asin")),"parent_asin":p,"subreddit":"","post_id":"","post_title":"","comment_id":"",
 "review_title":txt(r.get("title")),"comment":body,"category":"待分析","dedup_key":h})
 if len(rows)>=MAX_KEEP:break
 if rs%2000000==0:print(f"{CAT} reviews_scanned={rs:,} kept={len(rows):,}",flush=True)
fields=list(rows[0].keys()) if rows else ["platform","source_type","source_url","date","rating_or_score","verified_purchase","helpful_vote","brand","model","asin","parent_asin","subreddit","post_id","post_title","comment_id","review_title","comment","category","dedup_key"]
with open(OUT/f"{CAT}_walking_pad_reviews.csv","w",encoding="utf-8-sig",newline="") as f:
 w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
st={"category":CAT,"meta_scanned":ms,"matched_products":len(products),"reviews_scanned":rs,"raw_matches":raw,"dedup_kept":len(rows)}
(OUT/f"{CAT}_stats.json").write_text(json.dumps(st,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(st),flush=True)
