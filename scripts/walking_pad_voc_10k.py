#!/usr/bin/env python3
import csv, json, os, re, hashlib, gzip, io, time, random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

TARGET = int(os.getenv("TARGET_REVIEWS", "105000"))
MIN_VALID = int(os.getenv("MIN_VALID", "100000"))
OUTDIR = Path(os.getenv("OUTDIR", "voc_output"))
OUTDIR.mkdir(parents=True, exist_ok=True)

META_URL = "https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw/meta_categories/meta_Sports_and_Outdoors.jsonl.gz"
REVIEWS_URL = "https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw/review_categories/Sports_and_Outdoors.jsonl.gz"
ARCTIC = "https://arctic-shift.photon-reddit.com/api"

KEYWORDS = [
    "walking pad","walkingpad","under desk treadmill","under-desk treadmill",
    "desk treadmill","walking treadmill","portable treadmill","compact treadmill",
    "foldable treadmill","folding treadmill","mini treadmill","2 in 1 treadmill",
    "2-in-1 treadmill","home office treadmill","treadmill for office",
    "treadmill under desk","walking machine"
]
BRANDS = [
    "walkingpad","kingsmith","urevo","deerrun","sperax","egofit","goyouth",
    "goplus","merach","lifespan","sunny health","toputure","maksone","wellfit",
    "axefit","motiongrey","freepi","vitalwalk"
]
CATEGORY_PATTERNS = {
    "安全/召回": r"recall|fire|burn|smoke|unsafe|fall|fell|injur|shock|sudden stop|abrupt stop|almost fell",
    "耐久/质量": r"fail|broke|broken|stopped working|died|motor|overheat|hot|burnt|squeak|grind|lasted",
    "跑带/稳定性": r"belt.*slip|slipping|belt.*drift|belt.*shift|center.*belt|align|wobbl|unstable|jerk",
    "噪音/振动": r"noisy|loud|noise|quiet|vibrat|stomp|downstairs|neighbor|creak",
    "尺寸/适配": r"too short|too narrow|wider|longer|stride|tall|height|width|capacity|weight limit",
    "收纳/便携": r"fold|stor(e|age)|under the bed|under bed|under sofa|under couch|upright|vertical|heavy|wheel",
    "App/遥控/数据": r"app|bluetooth|remote|disconnect|apple health|apple watch|subscription",
    "售后/保修": r"warranty|refund|return|customer service|support|replacement|parts|repair",
    "维护/跑带": r"lubricat|maintenance|clean|tension|calibrat|adjust",
    "速度/坡度/参数": r"incline|speed|mph|km/h|slows|slowing|faster",
    "人体工学/办公": r"handle|work from home|wfh|desk|meeting|zoom|typing|phone holder",
    "价格/价值": r"expensive|overpriced|price|worth|cheap|value",
    "运输/到货": r"arrived damaged|damaged|shipping|delivery|missing|box",
}

FIELDS = [
    "platform","source_type","source_url","date","rating_or_score","verified_purchase","helpful_vote",
    "brand","model","asin","parent_asin","subreddit","post_id","post_title","comment_id",
    "review_title","comment","category","dedup_key"
]

def norm(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())

def as_text(v):
    if v is None: return ""
    if isinstance(v,(list,tuple)): return " ".join(map(str,v))
    if isinstance(v,dict): return json.dumps(v,ensure_ascii=False)
    return str(v)

def match_product(row):
    blob = norm(" ".join([
        as_text(row.get("title")), as_text(row.get("description")),
        as_text(row.get("features")), as_text(row.get("categories")), as_text(row.get("store"))
    ]))
    if any(k in blob for k in KEYWORDS):
        return True
    if any(b in blob for b in BRANDS) and "treadmill" in blob and any(x in blob for x in ["walking","under desk","foldable","folding","compact","portable","2 in 1","2-in-1","mini"]):
        return True
    return False

def classify(text):
    low=norm(text); best=("其他/待聚类",0)
    for cat,pat in CATEGORY_PATTERNS.items():
        n=len(re.findall(pat,low,flags=re.I))
        if n>best[1]: best=(cat,n)
    return best[0]

def hash_text(text, context=""):
    return hashlib.sha256((norm(text)+"|"+norm(context)).encode("utf-8")).hexdigest()

def iso_date(ts):
    try:
        ts=float(ts)
        if ts>10**12: ts/=1000
        return datetime.fromtimestamp(ts,tz=timezone.utc).date().isoformat()
    except Exception:
        return ""

def iter_jsonl_gz(url,label):
    print(f"Streaming {label}: {url}",flush=True)
    headers={"User-Agent":"Mozilla/5.0 walking-pad-voc-research/2.0"}
    with requests.get(url,stream=True,timeout=(30,900),headers=headers) as r:
        r.raise_for_status(); r.raw.decode_content=False
        with gzip.GzipFile(fileobj=r.raw,mode="rb") as gz:
            txt=io.TextIOWrapper(gz,encoding="utf-8",errors="replace")
            for line in txt:
                line=line.strip()
                if not line: continue
                try: yield json.loads(line)
                except json.JSONDecodeError: continue

def request_json(url, params=None, retries=4, timeout=45):
    headers={"User-Agent":"walking-pad-voc-research/2.0"}
    for i in range(retries):
        try:
            r=requests.get(url,params=params,headers=headers,timeout=timeout)
            if r.status_code==200:
                return r.json()
            if r.status_code in (429,500,502,503,504,422):
                time.sleep(min(8,1.5*(i+1))+random.random())
                continue
            return {"data":[],"_status":r.status_code,"_text":r.text[:300]}
        except Exception as e:
            if i==retries-1: return {"data":[],"_error":repr(e)}
            time.sleep(min(8,1.5*(i+1))+random.random())
    return {"data":[]}

# ---------- AMAZON: full Sports & Outdoors scan ----------
products={}
meta_scanned=0
for row in iter_jsonl_gz(META_URL,"Sports & Outdoors metadata"):
    meta_scanned+=1
    if match_product(row):
        parent=str(row.get("parent_asin") or "")
        if parent:
            products[parent]={
                "parent_asin":parent,"title":as_text(row.get("title")),"brand":as_text(row.get("store")),
                "rating_number":row.get("rating_number"),"average_rating":row.get("average_rating"),"price":row.get("price"),
            }
    if meta_scanned%200000==0:
        print(f"metadata scanned={meta_scanned:,}; matched products={len(products):,}",flush=True)

rating_sum=sum(int(p.get("rating_number") or 0) for p in products.values())
print(f"Amazon metadata complete: scanned={meta_scanned:,}; matched_products={len(products):,}; rating_number_sum={rating_sum:,}",flush=True)
with open(OUTDIR/"matched_products.csv","w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=["parent_asin","title","brand","rating_number","average_rating","price"])
    w.writeheader(); w.writerows(products.values())

all_rows=[]
seen=set()
cats=Counter(); platform_counts=Counter()
amazon_scanned=amazon_raw=0

for rv in iter_jsonl_gz(REVIEWS_URL,"Sports & Outdoors reviews"):
    amazon_scanned+=1
    parent=str(rv.get("parent_asin") or "")
    if parent not in products:
        if amazon_scanned%1000000==0:
            print(f"Amazon scanned={amazon_scanned:,}; kept={len(all_rows):,}",flush=True)
        continue
    text=as_text(rv.get("text")).strip()
    if len(text)<8: continue
    title=as_text(rv.get("title")); p=products[parent]
    dk=hash_text(text,parent)
    amazon_raw+=1
    if dk in seen: continue
    seen.add(dk)
    row={
        "platform":"Amazon Reviews 2023","source_type":"historical product review",
        "source_url":f"https://www.amazon.com/dp/{parent}","date":iso_date(rv.get("timestamp")),
        "rating_or_score":rv.get("rating"),"verified_purchase":rv.get("verified_purchase"),"helpful_vote":rv.get("helpful_vote"),
        "brand":p["brand"],"model":p["title"],"asin":as_text(rv.get("asin")),"parent_asin":parent,
        "subreddit":"","post_id":"","post_title":"","comment_id":"","review_title":title,"comment":text,
        "category":classify(title+" "+text),"dedup_key":dk
    }
    all_rows.append(row); cats[row["category"]]+=1; platform_counts[row["platform"]]+=1
    if amazon_scanned%1000000==0:
        print(f"Amazon scanned={amazon_scanned:,}; raw={amazon_raw:,}; dedup={len(all_rows):,}",flush=True)

print(f"Amazon full scan complete: scanned={amazon_scanned:,}; raw={amazon_raw:,}; dedup={len(all_rows):,}",flush=True)

# ---------- REDDIT: discover relevant posts, then pull whole comment trees ----------
# High-purity communities can be collected broadly; larger communities use keyword/year slices.
community_specs=[
    ("WalkingPads", None, 2023),
    ("walkingdesks", None, 2018),
    ("treadmills", ["walking pad","under desk treadmill","desk treadmill","walking treadmill"], 2019),
    ("StandingDesks", ["walking pad","under desk treadmill","desk treadmill"], 2019),
    ("WFH", ["walking pad","under desk treadmill","desk treadmill"], 2020),
    ("walking", ["walking pad","under desk treadmill"], 2020),
    ("workingmoms", ["walking pad","under desk treadmill"], 2020),
    ("PetiteFitness", ["walking pad","under desk treadmill"], 2020),
    ("loseit", ["walking pad","under desk treadmill"], 2020),
    ("CICO", ["walking pad","under desk treadmill"], 2020),
]
now_year=2027
post_map={}

def collect_posts_for_slice(sub, query, year):
    found=[]; after=f"{year}-01-01"; before=f"{year+1}-01-01"; last_after=after
    for page in range(120):
        params={"subreddit":sub,"limit":100,"sort":"asc","after":last_after,"before":before,
                "fields":"id,title,selftext,created_utc,num_comments,subreddit,permalink"}
        if query: params["query"]=query
        j=request_json(f"{ARCTIC}/posts/search",params=params,retries=5,timeout=60)
        data=j.get("data") or []
        if not data: break
        found.extend(data)
        mx=max(int(x.get("created_utc") or 0) for x in data)
        if mx<=0: break
        nxt=mx+1
        # avoid loop on same timestamp
        if str(nxt)==str(last_after): break
        last_after=str(nxt)
        if len(data)<100: break
        time.sleep(0.08)
    return found

for sub,queries,start_year in community_specs:
    qlist=queries or [None]
    for year in range(start_year,now_year):
        for q in qlist:
            data=collect_posts_for_slice(sub,q,year)
            for p in data:
                pid=str(p.get("id") or "")
                if not pid: continue
                # local relevance safety for broad subreddits
                blob=norm(as_text(p.get("title"))+" "+as_text(p.get("selftext")))
                if queries and not any(k in blob for k in ["walking pad","walkingpad","under desk treadmill","desk treadmill","walking treadmill"]):
                    continue
                post_map[pid]=p
            if data:
                print(f"Reddit discovery: r/{sub} {year} query={q!r}: fetched={len(data):,}, unique_relevant_posts={len(post_map):,}",flush=True)
            time.sleep(0.15)

print(f"Reddit relevant posts discovered={len(post_map):,}; declared comments={sum(int(p.get('num_comments') or 0) for p in post_map.values()):,}",flush=True)

# Prioritize posts with more comments, but cover all until target hit.
posts=sorted(post_map.values(),key=lambda p:int(p.get("num_comments") or 0),reverse=True)

def flatten_tree(nodes):
    out=[]
    def walk(item):
        if isinstance(item,list):
            for x in item: walk(x)
            return
        if not isinstance(item,dict): return
        if item.get("kind")=="t1" and isinstance(item.get("data"),dict):
            d=item["data"]; out.append(d)
            rep=d.get("replies")
            if isinstance(rep,dict):
                children=((rep.get("data") or {}).get("children") or [])
                walk(children)
        elif "data" in item and isinstance(item["data"],list):
            walk(item["data"])
    walk(nodes)
    return out

def fetch_tree(post):
    pid=str(post.get("id"))
    params={"link_id":f"t3_{pid}","limit":9999,"start_breadth":999,"start_depth":999}
    j=request_json(f"{ARCTIC}/comments/tree",params=params,retries=5,timeout=90)
    return pid,j.get("data") or []

reddit_added=0
processed_posts=0
# Work in batches to avoid hammering the service.
for batch_start in range(0,len(posts),16):
    if len(all_rows)>=TARGET: break
    batch=posts[batch_start:batch_start+16]
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs={ex.submit(fetch_tree,p):p for p in batch}
        for fut in as_completed(futs):
            post=futs[fut]
            try: pid,nodes=fut.result()
            except Exception: continue
            comments=flatten_tree(nodes)
            processed_posts+=1
            for c in comments:
                body=as_text(c.get("body")).strip()
                if len(body)<5 or body in ("[deleted]","[removed]"): continue
                cid=str(c.get("id") or "")
                context=f"reddit:{cid or pid}"
                dk=hash_text(body,context)
                if dk in seen: continue
                seen.add(dk)
                permalink=as_text(c.get("permalink"))
                url=("https://www.reddit.com"+permalink) if permalink.startswith("/") else permalink
                row={
                    "platform":"Reddit","source_type":"comment","source_url":url,
                    "date":iso_date(c.get("created_utc")),"rating_or_score":c.get("score"),
                    "verified_purchase":"","helpful_vote":"","brand":"","model":"","asin":"","parent_asin":"",
                    "subreddit":as_text(post.get("subreddit")),"post_id":pid,"post_title":as_text(post.get("title")),
                    "comment_id":cid,"review_title":"","comment":body,
                    "category":classify(as_text(post.get("title"))+" "+body),"dedup_key":dk
                }
                all_rows.append(row); reddit_added+=1; cats[row["category"]]+=1; platform_counts[row["platform"]]+=1
                if len(all_rows)>=TARGET: break
            if processed_posts%50==0:
                print(f"Reddit trees processed={processed_posts:,}; Reddit comments added={reddit_added:,}; total={len(all_rows):,}",flush=True)
            if len(all_rows)>=TARGET: break
    time.sleep(0.15)

print(f"Reddit stage complete: processed_posts={processed_posts:,}; comments_added={reddit_added:,}; combined={len(all_rows):,}",flush=True)

# ---------- OUTPUT ----------
# Keep only TARGET if more were collected.
if len(all_rows)>TARGET: all_rows=all_rows[:TARGET]

csv_path=OUTDIR/"walking_pad_voc_100k.csv"
with open(csv_path,"w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerows(all_rows)

# Platform/category summaries
with open(OUTDIR/"summary_by_category.csv","w",encoding="utf-8-sig",newline="") as f:
    w=csv.writer(f); w.writerow(["category","count"])
    for k,v in cats.most_common(): w.writerow([k,v])
with open(OUTDIR/"summary_by_platform.csv","w",encoding="utf-8-sig",newline="") as f:
    w=csv.writer(f); w.writerow(["platform","count"])
    for k,v in platform_counts.most_common(): w.writerow([k,v])

stats={
    "target":TARGET,"minimum":MIN_VALID,"final_rows":len(all_rows),
    "amazon":{"meta_scanned":meta_scanned,"matched_products":len(products),"rating_number_sum":rating_sum,
              "reviews_scanned":amazon_scanned,"raw_matches":amazon_raw,
              "dedup_kept":platform_counts.get("Amazon Reviews 2023",0)},
    "reddit":{"posts_discovered":len(post_map),"trees_processed":processed_posts,
              "comments_kept":platform_counts.get("Reddit",0)},
    "categories":dict(Counter(r["category"] for r in all_rows)),
    "platforms":dict(Counter(r["platform"] for r in all_rows)),
}
with open(OUTDIR/"stats.json","w",encoding="utf-8") as f:
    json.dump(stats,f,ensure_ascii=False,indent=2)
print(json.dumps(stats,ensure_ascii=False),flush=True)
if len(all_rows)<MIN_VALID:
    raise SystemExit(f"Only {len(all_rows):,} rows collected; need at least {MIN_VALID:,}.")
