#!/usr/bin/env python3
import csv, json, os, re, hashlib, gzip, io
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import requests

TARGET=int(os.getenv("TARGET_REVIEWS","100000"))
MIN_VALID=int(os.getenv("MIN_VALID","100000"))
OUTDIR=Path(os.getenv("OUTDIR","voc_output")); OUTDIR.mkdir(parents=True,exist_ok=True)
BASE="https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw"
CATEGORIES=[
    "Sports_and_Outdoors",
    "Home_and_Kitchen",
    "Office_Products",
    "Health_and_Household",
    "Industrial_and_Scientific",
    "Tools_and_Home_Improvement",
]

KEYWORDS=[
    "walking pad","walkingpad","under desk treadmill","under-desk treadmill",
    "desk treadmill","walking treadmill","portable treadmill","compact treadmill",
    "foldable treadmill","folding treadmill","mini treadmill","2 in 1 treadmill",
    "2-in-1 treadmill","home office treadmill","treadmill for office",
    "treadmill under desk","walking machine"
]
BRANDS=[
    "walkingpad","kingsmith","urevo","deerrun","sperax","egofit","goyouth",
    "goplus","merach","lifespan","sunny health","toputure","maksone","wellfit",
    "axefit","motiongrey","freepi","vitalwalk"
]
CATEGORY_PATTERNS={
    "安全/召回":r"recall|fire|burn|smoke|unsafe|fall|fell|injur|shock|sudden stop|abrupt stop|almost fell",
    "耐久/质量":r"fail|broke|broken|stopped working|died|motor|overheat|hot|burnt|squeak|grind|lasted",
    "跑带/稳定性":r"belt.*slip|slipping|belt.*drift|belt.*shift|center.*belt|align|wobbl|unstable|jerk",
    "噪音/振动":r"noisy|loud|noise|quiet|vibrat|stomp|downstairs|neighbor|creak",
    "尺寸/适配":r"too short|too narrow|wider|longer|stride|tall|height|width|capacity|weight limit",
    "收纳/便携":r"fold|stor(e|age)|under the bed|under bed|under sofa|under couch|upright|vertical|heavy|wheel",
    "App/遥控/数据":r"app|bluetooth|remote|disconnect|apple health|apple watch|subscription",
    "售后/保修":r"warranty|refund|return|customer service|support|replacement|parts|repair",
    "维护/跑带":r"lubricat|maintenance|clean|tension|calibrat|adjust",
    "速度/坡度/参数":r"incline|speed|mph|km/h|slows|slowing|faster",
    "人体工学/办公":r"handle|work from home|wfh|desk|meeting|zoom|typing|phone holder",
    "价格/价值":r"expensive|overpriced|price|worth|cheap|value",
    "运输/到货":r"arrived damaged|damaged|shipping|delivery|missing|box",
}

FIELDS=["platform","amazon_category","source_type","source_url","date","rating","verified_purchase","helpful_vote",
        "brand","model","asin","parent_asin","review_title","comment","category","dedup_key"]

def norm(s): return re.sub(r"\s+"," ",str(s or "").strip().lower())
def as_text(v):
    if v is None:return ""
    if isinstance(v,(list,tuple)):return " ".join(map(str,v))
    if isinstance(v,dict):return json.dumps(v,ensure_ascii=False)
    return str(v)
def match_product(row):
    blob=norm(" ".join([as_text(row.get("title")),as_text(row.get("description")),
                        as_text(row.get("features")),as_text(row.get("categories")),as_text(row.get("store"))]))
    if any(k in blob for k in KEYWORDS): return True
    return any(b in blob for b in BRANDS) and "treadmill" in blob and any(
        x in blob for x in ["walking","under desk","foldable","folding","compact","portable","2 in 1","2-in-1","mini"])
def classify(text):
    low=norm(text); best=("其他/待聚类",0)
    for cat,pat in CATEGORY_PATTERNS.items():
        n=len(re.findall(pat,low,flags=re.I))
        if n>best[1]: best=(cat,n)
    return best[0]
def dkey(text, parent): return hashlib.sha256((norm(text)+"|"+norm(parent)).encode()).hexdigest()
def iso_date(ts):
    try:
        x=float(ts); x=x/1000 if x>10**12 else x
        return datetime.fromtimestamp(x,tz=timezone.utc).date().isoformat()
    except:return ""
def iter_gz(url,label):
    print(f"Streaming {label}: {url}",flush=True)
    with requests.get(url,stream=True,timeout=(30,1200),headers={"User-Agent":"walking-pad-voc-research/3.0"}) as r:
        r.raise_for_status(); r.raw.decode_content=False
        with gzip.GzipFile(fileobj=r.raw,mode="rb") as gz:
            txt=io.TextIOWrapper(gz,encoding="utf-8",errors="replace")
            for line in txt:
                try: yield json.loads(line)
                except: continue

all_rows=[]; seen=set(); cats=Counter(); platform_counts=Counter()
product_rows=[]; stats_by_cat={}
total_meta=total_reviews=total_raw=0

for amazon_cat in CATEGORIES:
    if len(all_rows)>=TARGET: break
    meta_url=f"{BASE}/meta_categories/meta_{amazon_cat}.jsonl.gz"
    rev_url=f"{BASE}/review_categories/{amazon_cat}.jsonl.gz"
    products={}; meta_scanned=0
    try:
        for row in iter_gz(meta_url,f"{amazon_cat} metadata"):
            meta_scanned+=1
            if match_product(row):
                parent=str(row.get("parent_asin") or "")
                if parent:
                    products[parent]={
                        "parent_asin":parent,"title":as_text(row.get("title")),"brand":as_text(row.get("store")),
                        "rating_number":row.get("rating_number"),"average_rating":row.get("average_rating"),
                        "price":row.get("price"),"amazon_category":amazon_cat
                    }
            if meta_scanned%250000==0:
                print(f"{amazon_cat} metadata={meta_scanned:,}; products={len(products):,}",flush=True)
    except requests.HTTPError as e:
        print(f"SKIP {amazon_cat} metadata: {e}",flush=True); continue

    rating_sum=sum(int(p.get("rating_number") or 0) for p in products.values())
    print(f"{amazon_cat} metadata complete: scanned={meta_scanned:,}; matched={len(products):,}; ratings={rating_sum:,}",flush=True)
    total_meta+=meta_scanned
    product_rows.extend(products.values())
    if not products:
        stats_by_cat[amazon_cat]={"meta_scanned":meta_scanned,"matched_products":0,"reviews_scanned":0,"raw_matches":0,"dedup_added":0}
        continue

    reviews_scanned=raw=added=0
    try:
        for rv in iter_gz(rev_url,f"{amazon_cat} reviews"):
            reviews_scanned+=1
            parent=str(rv.get("parent_asin") or "")
            if parent not in products:
                if reviews_scanned%1000000==0:
                    print(f"{amazon_cat} reviews={reviews_scanned:,}; total kept={len(all_rows):,}",flush=True)
                continue
            text=as_text(rv.get("text")).strip()
            if len(text)<8: continue
            raw+=1
            dk=dkey(text,parent)
            if dk in seen: continue
            seen.add(dk)
            p=products[parent]; title=as_text(rv.get("title"))
            row={"platform":"Amazon Reviews 2023","amazon_category":amazon_cat,
                 "source_type":"historical product review","source_url":f"https://www.amazon.com/dp/{parent}",
                 "date":iso_date(rv.get("timestamp")),"rating":rv.get("rating"),
                 "verified_purchase":rv.get("verified_purchase"),"helpful_vote":rv.get("helpful_vote"),
                 "brand":p["brand"],"model":p["title"],"asin":as_text(rv.get("asin")),"parent_asin":parent,
                 "review_title":title,"comment":text,"category":classify(title+" "+text),"dedup_key":dk}
            all_rows.append(row); added+=1; cats[row["category"]]+=1; platform_counts[row["platform"]]+=1
            if len(all_rows)>=TARGET: break
            if reviews_scanned%1000000==0:
                print(f"{amazon_cat} reviews={reviews_scanned:,}; raw={raw:,}; added={added:,}; total={len(all_rows):,}",flush=True)
    except requests.HTTPError as e:
        print(f"SKIP {amazon_cat} reviews: {e}",flush=True)
    total_reviews+=reviews_scanned; total_raw+=raw
    stats_by_cat[amazon_cat]={"meta_scanned":meta_scanned,"matched_products":len(products),"rating_number_sum":rating_sum,
                              "reviews_scanned":reviews_scanned,"raw_matches":raw,"dedup_added":added}
    print(f"{amazon_cat} done: scanned={reviews_scanned:,}; raw={raw:,}; added={added:,}; COMBINED={len(all_rows):,}",flush=True)

# Write CSV
csv_path=OUTDIR/"walking_pad_voc_100k.csv"
with open(csv_path,"w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerows(all_rows)

# Products
prod_fields=["amazon_category","parent_asin","title","brand","rating_number","average_rating","price"]
with open(OUTDIR/"matched_products.csv","w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=prod_fields); w.writeheader()
    for p in product_rows: w.writerow({k:p.get(k) for k in prod_fields})

# Summaries
with open(OUTDIR/"summary_by_category.csv","w",encoding="utf-8-sig",newline="") as f:
    w=csv.writer(f); w.writerow(["category","count"]); w.writerows(cats.most_common())
with open(OUTDIR/"summary_by_amazon_category.csv","w",encoding="utf-8-sig",newline="") as f:
    w=csv.writer(f); w.writerow(["amazon_category","dedup_added","raw_matches","reviews_scanned","matched_products"])
    for k,v in stats_by_cat.items(): w.writerow([k,v.get("dedup_added"),v.get("raw_matches"),v.get("reviews_scanned"),v.get("matched_products")])

# XLSX in write-only mode
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
wb=Workbook(write_only=True)
ws=wb.create_sheet("评论明细_All"); ws.append(FIELDS)
for r in all_rows: ws.append([r.get(h,"") for h in FIELDS])
sw=wb.create_sheet("汇总"); sw.append(["指标","值"])
for k,v in [
    ("实际去重评论",len(all_rows)),("目标",TARGET),("扫描商品元数据",total_meta),
    ("扫描评论",total_reviews),("原始匹配评论",total_raw),("匹配商品记录",len(product_rows)),
    ("生成时间",datetime.now(timezone.utc).isoformat())
]: sw.append([k,v])
sw.append([]); sw.append(["痛点分类","样本数"])
for k,v in cats.most_common(): sw.append([k,v])
cw=wb.create_sheet("Amazon类目"); cw.append(["类目","新增去重评论","原始命中","扫描评论","匹配商品"])
for k,v in stats_by_cat.items(): cw.append([k,v.get("dedup_added"),v.get("raw_matches"),v.get("reviews_scanned"),v.get("matched_products")])
pw=wb.create_sheet("匹配商品"); pw.append(prod_fields)
for p in product_rows: pw.append([p.get(h,"") for h in prod_fields])
xlsx=OUTDIR/"walking_pad_voc_100k.xlsx"; wb.save(xlsx)

stats={"target":TARGET,"minimum":MIN_VALID,"final_rows":len(all_rows),"categories_scanned":stats_by_cat,
       "meta_scanned_total":total_meta,"reviews_scanned_total":total_reviews,"raw_matches_total":total_raw,
       "matched_product_records":len(product_rows),"pain_categories":dict(cats)}
with open(OUTDIR/"stats.json","w",encoding="utf-8") as f:json.dump(stats,f,ensure_ascii=False,indent=2)
print(json.dumps(stats,ensure_ascii=False),flush=True)
if len(all_rows)<MIN_VALID: raise SystemExit(f"Only {len(all_rows):,} rows; need {MIN_VALID:,}.")
