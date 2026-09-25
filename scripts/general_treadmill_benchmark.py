#!/usr/bin/env python3
import csv,json,os,re,hashlib,gzip,io
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import requests

TARGET=int(os.getenv("TARGET_REVIEWS","100000"))
OUTDIR=Path(os.getenv("OUTDIR","general_treadmill_output"));OUTDIR.mkdir(parents=True,exist_ok=True)
META="https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw/meta_categories/meta_Sports_and_Outdoors.jsonl.gz"
REV="https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw/review_categories/Sports_and_Outdoors.jsonl.gz"
CATS={
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
FIELDS=["platform","amazon_category","relevance_tier","source_type","source_url","date","rating","verified_purchase","helpful_vote","brand","model","asin","parent_asin","review_title","comment","category","dedup_key"]
def norm(s):return re.sub(r"\s+"," ",str(s or "").strip().lower())
def txt(v):
    if v is None:return ""
    if isinstance(v,(list,tuple)):return " ".join(map(str,v))
    if isinstance(v,dict):return json.dumps(v,ensure_ascii=False)
    return str(v)
def cls(s):
    low=norm(s);best=("其他/待聚类",0)
    for k,p in CATS.items():
        n=len(re.findall(p,low,re.I))
        if n>best[1]:best=(k,n)
    return best[0]
def dk(t,p):return hashlib.sha256((norm(t)+"|"+norm(p)).encode()).hexdigest()
def dt(ts):
    try:
        x=float(ts);x=x/1000 if x>1e12 else x
        return datetime.fromtimestamp(x,tz=timezone.utc).date().isoformat()
    except:return ""
def it(url):
    with requests.get(url,stream=True,timeout=(30,1200),headers={"User-Agent":"walking-pad-voc-research/6.0"}) as r:
        r.raise_for_status();r.raw.decode_content=False
        with gzip.GzipFile(fileobj=r.raw) as gz:
            f=io.TextIOWrapper(gz,encoding="utf-8",errors="replace")
            for line in f:
                try:yield json.loads(line)
                except:continue

products={};m=0
for x in it(META):
    m+=1;t=norm(txt(x.get("title")))
    if "treadmill" in t:
        p=str(x.get("parent_asin") or "")
        if p:products[p]={"title":txt(x.get("title")),"brand":txt(x.get("store"))}
    if m%100000==0:print(f"meta={m:,}; treadmill-title-products={len(products):,}",flush=True)
print(f"metadata done={m:,}; products={len(products):,}",flush=True)

rows=[];seen=set();scan=raw=0;cats=Counter()
for x in it(REV):
    scan+=1;p=str(x.get("parent_asin") or "")
    if p not in products:
        if scan%500000==0:print(f"reviews={scan:,}; kept={len(rows):,}",flush=True)
        continue
    body=txt(x.get("text")).strip()
    if len(body)<8:continue
    raw+=1;k=dk(body,p)
    if k in seen:continue
    seen.add(k);prod=products[p];title=txt(x.get("title"))
    row={"platform":"Amazon Reviews 2023","amazon_category":"Sports_and_Outdoors","relevance_tier":"Adjacent General Treadmill",
    "source_type":"historical treadmill benchmark review","source_url":f"https://www.amazon.com/dp/{p}",
    "date":dt(x.get("timestamp")),"rating":x.get("rating"),"verified_purchase":x.get("verified_purchase"),
    "helpful_vote":x.get("helpful_vote"),"brand":prod["brand"],"model":prod["title"],"asin":txt(x.get("asin")),
    "parent_asin":p,"review_title":title,"comment":body,"category":cls(title+" "+body),"dedup_key":k}
    rows.append(row);cats[row["category"]]+=1
    if len(rows)>=TARGET:break
    if scan%500000==0:print(f"reviews={scan:,}; raw={raw:,}; kept={len(rows):,}",flush=True)
with open(OUTDIR/"general_treadmill_2023.csv","w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
stats={"target":TARGET,"final_rows":len(rows),"matched_products":len(products),"reviews_scanned":scan,"raw_matches":raw,"pain_categories":dict(cats)}
with open(OUTDIR/"stats.json","w",encoding="utf-8") as f:json.dump(stats,f,ensure_ascii=False,indent=2)
print(json.dumps(stats,ensure_ascii=False),flush=True)
