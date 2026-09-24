#!/usr/bin/env python3
import csv, json, os, time, random, re, hashlib
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

TARGET = int(os.getenv("TARGET_REDDIT", "50000"))
OUTDIR = Path(os.getenv("OUTDIR", "reddit_output"))
OUTDIR.mkdir(parents=True, exist_ok=True)
ARCTIC = "https://arctic-shift.photon-reddit.com/api"
UA = {"User-Agent":"walking-pad-voc-research/3.0"}

TERMS = ["walking pad","walkingpad","under desk treadmill","desk treadmill","walking treadmill","walking desk","under desk"]
PURE_SUBS = [
    ("WalkingPads", 2023),
    ("walkingdesks", 2018),
]
QUERY_SUBS = [
    ("treadmills", 2019),
    ("StandingDesks", 2019),
    ("WFH", 2020),
    ("walking", 2020),
    ("workingmoms", 2020),
    ("PetiteFitness", 2020),
    ("loseit", 2020),
    ("CICO", 2020),
    ("homeoffice", 2020),
    ("productivity", 2020),
    ("desksetup", 2020),
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

def norm(s):
    return re.sub(r"\s+"," ",str(s or "").strip().lower())

def classify(text):
    low=norm(text); best=("其他/待聚类",0)
    for cat,pat in CATEGORY_PATTERNS.items():
        n=len(re.findall(pat,low,re.I))
        if n>best[1]: best=(cat,n)
    return best[0]

def epoch_date(ts):
    try: return datetime.fromtimestamp(float(ts),tz=timezone.utc).date().isoformat()
    except: return ""

def year_bounds(year):
    a=int(datetime(year,1,1,tzinfo=timezone.utc).timestamp())
    b=int(datetime(year+1,1,1,tzinfo=timezone.utc).timestamp())
    return a,b

def month_bounds(year,month):
    a=datetime(year,month,1,tzinfo=timezone.utc)
    if month==12: b=datetime(year+1,1,1,tzinfo=timezone.utc)
    else: b=datetime(year,month+1,1,tzinfo=timezone.utc)
    return int(a.timestamp()), int(b.timestamp())

def get_json(path, params=None, retries=6, timeout=60):
    url=ARCTIC+path
    last=None
    for i in range(retries):
        try:
            r=requests.get(url,params=params,headers=UA,timeout=timeout)
            if r.status_code==200:
                return r.json()
            last=(r.status_code,r.text[:200])
            if r.status_code in (422,429,500,502,503,504):
                time.sleep(min(12,1.5*(i+1))+random.random())
                continue
            break
        except Exception as e:
            last=repr(e)
            time.sleep(min(12,1.5*(i+1))+random.random())
    return {"data":[],"_err":str(last)}

def paginate_posts(sub, after, before, query=None, max_pages=200):
    out=[]; cursor=after
    for _ in range(max_pages):
        params={"subreddit":sub,"limit":100,"sort":"asc","after":cursor,"before":before}
        if query: params["query"]=query
        j=get_json("/posts/search",params,timeout=70)
        data=j.get("data") or []
        if not data: break
        out.extend(data)
        mx=max(int(x.get("created_utc") or 0) for x in data)
        if mx<=cursor: break
        cursor=mx+1
        if len(data)<100: break
        time.sleep(0.06)
    return out

def discover_query_slice(sub, term, year):
    a,b=year_bounds(year)
    data=paginate_posts(sub,a,b,term,max_pages=80)
    if data:
        return data
    # Fallback to smaller monthly windows if annual full-text search timed out.
    allm=[]
    for m in range(1,13):
        ma,mb=month_bounds(year,m)
        d=paginate_posts(sub,ma,mb,term,max_pages=30)
        allm.extend(d)
        time.sleep(0.04)
    return allm

posts={}
# High-purity subs: all posts
for sub,start in PURE_SUBS:
    for year in range(start,2027):
        a,b=year_bounds(year)
        data=paginate_posts(sub,a,b,None,max_pages=200)
        for p in data:
            pid=str(p.get("id") or "")
            if pid: posts[pid]=p
        print(f"discover pure r/{sub} {year}: fetched={len(data):,}, unique={len(posts):,}",flush=True)

# Larger subs: keyword searches, sliced by year with monthly fallback
for sub,start in QUERY_SUBS:
    for year in range(start,2027):
        for term in TERMS:
            data=discover_query_slice(sub,term,year)
            for p in data:
                pid=str(p.get("id") or "")
                if not pid: continue
                blob=norm(str(p.get("title") or "")+" "+str(p.get("selftext") or ""))
                if any(t in blob for t in TERMS):
                    posts[pid]=p
            if data:
                print(f"discover query r/{sub} {year} {term!r}: fetched={len(data):,}, unique={len(posts):,}",flush=True)
            time.sleep(0.05)

declared=sum(int(p.get("num_comments") or 0) for p in posts.values())
print(f"POST DISCOVERY COMPLETE unique_posts={len(posts):,} declared_comments={declared:,}",flush=True)

def flatten_tree(nodes):
    out=[]
    def walk(x):
        if isinstance(x,list):
            for y in x: walk(y)
            return
        if not isinstance(x,dict): return
        if x.get("kind")=="t1" and isinstance(x.get("data"),dict):
            d=x["data"]; out.append(d)
            rep=d.get("replies")
            if isinstance(rep,dict):
                walk(((rep.get("data") or {}).get("children") or []))
        elif isinstance(x.get("data"),list):
            walk(x["data"])
    walk(nodes)
    return out

def fetch_comments(post):
    pid=str(post.get("id") or "")
    j=get_json("/comments/tree",{
        "link_id":"t3_"+pid,
        "limit":9999,
        "start_breadth":999,
        "start_depth":999
    },retries=5,timeout=90)
    return post, flatten_tree(j.get("data") or [])

ordered=sorted(posts.values(), key=lambda p:int(p.get("num_comments") or 0), reverse=True)
seen_ids=set(); seen_hashes=set(); rows=[]; processed=0

for start in range(0,len(ordered),20):
    if len(rows)>=TARGET: break
    batch=ordered[start:start+20]
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs=[ex.submit(fetch_comments,p) for p in batch if int(p.get("num_comments") or 0)>0]
        for fut in as_completed(futs):
            try: post,comments=fut.result()
            except Exception: continue
            processed+=1
            pid=str(post.get("id") or "")
            title=str(post.get("title") or "")
            sub=str(post.get("subreddit") or "")
            for c in comments:
                body=str(c.get("body") or "").strip()
                cid=str(c.get("id") or "")
                if len(body)<5 or body in ("[deleted]","[removed]"): continue
                if cid and cid in seen_ids: continue
                h=hashlib.sha256(norm(body).encode("utf-8")).hexdigest()
                # Exact duplicate text by different users is also collapsed for VOC counting.
                if h in seen_hashes: continue
                if cid: seen_ids.add(cid)
                seen_hashes.add(h)
                permalink=str(c.get("permalink") or "")
                url=("https://www.reddit.com"+permalink) if permalink.startswith("/") else permalink
                rows.append({
                    "platform":"Reddit",
                    "source_type":"comment",
                    "source_url":url,
                    "date":epoch_date(c.get("created_utc")),
                    "rating_or_score":c.get("score"),
                    "verified_purchase":"",
                    "helpful_vote":"",
                    "brand":"",
                    "model":"",
                    "asin":"",
                    "parent_asin":"",
                    "subreddit":sub,
                    "post_id":pid,
                    "post_title":title,
                    "comment_id":cid,
                    "review_title":"",
                    "comment":body,
                    "category":classify(title+" "+body),
                    "dedup_key":h
                })
                if len(rows)>=TARGET: break
            if processed%50==0:
                print(f"trees_processed={processed:,}; comments_kept={len(rows):,}; remaining_posts={len(ordered)-start:,}",flush=True)
            if len(rows)>=TARGET: break
    time.sleep(0.12)

fields=["platform","source_type","source_url","date","rating_or_score","verified_purchase","helpful_vote","brand","model","asin","parent_asin","subreddit","post_id","post_title","comment_id","review_title","comment","category","dedup_key"]
out=OUTDIR/"reddit_walking_pad_comments_50k.csv"
with open(out,"w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

stats={"target":TARGET,"posts_discovered":len(posts),"declared_comments":declared,"trees_processed":processed,"comments_kept":len(rows)}
with open(OUTDIR/"reddit_stats.json","w",encoding="utf-8") as f: json.dump(stats,f,ensure_ascii=False,indent=2)
print(json.dumps(stats,ensure_ascii=False),flush=True)
if len(rows)<TARGET:
    raise SystemExit(f"Reddit only produced {len(rows):,} comments; target={TARGET:,}")
