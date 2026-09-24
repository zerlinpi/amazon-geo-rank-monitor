#!/usr/bin/env python3
import csv, json, os, time, random, re, hashlib
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

TARGET=int(os.getenv("TARGET_REDDIT","50000"))
OUTDIR=Path(os.getenv("OUTDIR","reddit_fast_output")); OUTDIR.mkdir(parents=True,exist_ok=True)
BASE="https://arctic-shift.photon-reddit.com/api/comments/search"
UA={"User-Agent":"walking-pad-voc-research/4.0"}

PURE=[("WalkingPads",2023),("walkingdesks",2018)]
FILTERED_SUBS=["treadmills","StandingDesks","WFH","walking","workingmoms","PetiteFitness","loseit","CICO","homeoffice","productivity","fitness"]
TERMS=["walking pad","walkingpad","under desk treadmill","under-desk treadmill","desk treadmill","walking treadmill","treadmill desk","walking desk",
       "urevo","deerrun","sperax","kingsmith","egofit","goyouth","merach","toputure","wellfit"]
PATTERNS={
 "安全/召回":r"recall|fire|burn|smoke|unsafe|fall|fell|injur|shock|sudden stop|abrupt stop|almost fell",
 "耐久/质量":r"fail|broke|broken|stopped working|died|motor|overheat|hot|burnt|squeak|grind|lasted",
 "跑带/稳定性":r"belt.*slip|slipping|belt.*drift|belt.*shift|align|wobbl|unstable|jerk",
 "噪音/振动":r"noisy|loud|noise|quiet|vibrat|stomp|downstairs|neighbor|creak",
 "尺寸/适配":r"too short|too narrow|wider|longer|stride|tall|height|width|capacity|weight limit",
 "收纳/便携":r"fold|storage|store|under bed|under sofa|under couch|upright|vertical|heavy|wheel",
 "App/遥控/数据":r"app|bluetooth|remote|disconnect|apple health|apple watch|subscription",
 "售后/保修":r"warranty|refund|return|customer service|support|replacement|parts|repair",
 "维护/跑带":r"lubricat|maintenance|clean|tension|calibrat|adjust",
 "速度/坡度/参数":r"incline|speed|mph|km/h|slows|slowing|faster",
 "人体工学/办公":r"handle|work from home|wfh|desk|meeting|zoom|typing|phone holder",
 "价格/价值":r"expensive|overpriced|price|worth|cheap|value"
}
def norm(s): return re.sub(r"\s+"," ",str(s or "").strip().lower())
def classify(t):
    low=norm(t); best=("其他/待聚类",0)
    for k,p in PATTERNS.items():
        n=len(re.findall(p,low,re.I))
        if n>best[1]: best=(k,n)
    return best[0]
def iso(ts):
    try:return datetime.fromtimestamp(float(ts),tz=timezone.utc).date().isoformat()
    except:return ""
def req(params,retries=5):
    last=None
    for i in range(retries):
        try:
            r=requests.get(BASE,params=params,headers=UA,timeout=60)
            if r.status_code==200:
                j=r.json(); j["_status"]=200; return j
            last=(r.status_code,r.text[:100])
            if r.status_code in (422,429,500,502,503,504):
                time.sleep(1.2*(i+1)+random.random()); continue
            break
        except Exception as e:
            last=repr(e); time.sleep(1.2*(i+1)+random.random())
    return {"data":[],"_status":last[0] if isinstance(last,tuple) else None,"_err":str(last)}
def bounds(y):
    a=int(datetime(y,1,1,tzinfo=timezone.utc).timestamp()); b=int(datetime(y+1,1,1,tzinfo=timezone.utc).timestamp()); return a,b
def page_comments(sub,year,body=None,max_pages=300):
    a,b=bounds(year); cur=a; out=[]; timed=False
    for _ in range(max_pages):
        p={"subreddit":sub,"limit":100,"sort":"asc","after":cur,"before":b,
           "fields":"id,body,link_id,parent_id,created_utc,score,subreddit,author"}
        if body: p["body"]=body
        j=req(p); data=j.get("data") or []
        if not data:
            timed=(j.get("_status")==422); break
        out.extend(data)
        mx=max(int(x.get("created_utc") or 0) for x in data)
        if mx<=cur: break
        cur=mx+1
        if len(data)<100: break
        time.sleep(.03)
    return out,timed

jobs=[]
for sub,start in PURE:
    for y in range(start,2027): jobs.append(("pure",sub,y,None))
for sub in FILTERED_SUBS:
    for y in range(2020,2027):
        for term in TERMS: jobs.append(("filter",sub,y,term))

seen_id=set(); seen_hash=set(); rows=[]
def runjob(job):
    typ,sub,y,term=job
    data,timed=page_comments(sub,y,term if typ=="filter" else None)
    return job,data,timed

with ThreadPoolExecutor(max_workers=10) as ex:
    futs={ex.submit(runjob,j):j for j in jobs}
    done=0
    for fut in as_completed(futs):
        done+=1
        try:job,data,timed=fut.result()
        except Exception: continue
        typ,sub,y,term=job
        for c in data:
            body=str(c.get("body") or "").strip()
            if len(body)<5 or body in ("[deleted]","[removed]"):continue
            cid=str(c.get("id") or "")
            h=hashlib.sha256(norm(body).encode()).hexdigest()
            if (cid and cid in seen_id) or h in seen_hash:continue
            if cid:seen_id.add(cid)
            seen_hash.add(h)
            link=str(c.get("link_id") or "").replace("t3_","")
            url=f"https://www.reddit.com/comments/{link}/_/{cid}/" if link and cid else ""
            rows.append({
              "platform":"Reddit","source_type":"comment","source_url":url,"date":iso(c.get("created_utc")),
              "rating_or_score":c.get("score"),"verified_purchase":"","helpful_vote":"","brand":"","model":"","asin":"","parent_asin":"",
              "subreddit":str(c.get("subreddit") or sub),"post_id":link,"post_title":"","comment_id":cid,"review_title":"",
              "comment":body,"category":classify(body),"dedup_key":h
            })
            if len(rows)>=TARGET:break
        if data:
            print(f"job {done}/{len(jobs)} {typ} r/{sub} {y} {term!r}: got={len(data):,}, kept_total={len(rows):,}",flush=True)
        if done%50==0: print(f"progress jobs={done}/{len(jobs)} kept={len(rows):,}",flush=True)
        if len(rows)>=TARGET:
            for x in futs:x.cancel()
            break

fields=["platform","source_type","source_url","date","rating_or_score","verified_purchase","helpful_vote","brand","model","asin","parent_asin","subreddit","post_id","post_title","comment_id","review_title","comment","category","dedup_key"]
with open(OUTDIR/"reddit_walking_pad_comments_fast.csv","w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
stats={"target":TARGET,"jobs":len(jobs),"comments_kept":len(rows)}
with open(OUTDIR/"reddit_fast_stats.json","w",encoding="utf-8") as f:json.dump(stats,f,ensure_ascii=False,indent=2)
print(json.dumps(stats),flush=True)
if len(rows)<TARGET: raise SystemExit(f"Only {len(rows)} Reddit comments; target {TARGET}")
