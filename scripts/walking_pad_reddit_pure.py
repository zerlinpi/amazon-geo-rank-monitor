#!/usr/bin/env python3
import csv,json,os,time,random,re,hashlib
from datetime import datetime,timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
OUT=Path(os.getenv("OUTDIR","reddit_pure_output"));OUT.mkdir(parents=True,exist_ok=True)
BASE="https://arctic-shift.photon-reddit.com/api/comments/search";UA={"User-Agent":"walking-pad-voc-pure/1.0"}
SUBS=[("WalkingPads",2023),("walkingdesks",2018)]
def norm(s):return re.sub(r"\s+"," ",str(s or "").strip().lower())
def iso(ts):
 try:return datetime.fromtimestamp(float(ts),tz=timezone.utc).date().isoformat()
 except:return ""
def req(p):
 for i in range(5):
  try:
   r=requests.get(BASE,params=p,headers=UA,timeout=60)
   if r.status_code==200:return r.json()
   if r.status_code in (422,429,500,502,503,504):time.sleep(1+i+random.random());continue
   return {"data":[]}
  except:time.sleep(1+i+random.random())
 return {"data":[]}
def bounds(y):
 return int(datetime(y,1,1,tzinfo=timezone.utc).timestamp()),int(datetime(y+1,1,1,tzinfo=timezone.utc).timestamp())
def fetch(sub,y):
 a,b=bounds(y);cur=a;out=[]
 for pg in range(500):
  j=req({"subreddit":sub,"limit":100,"sort":"asc","after":cur,"before":b})
  d=j.get("data") or []
  if not d:break
  out.extend(d);mx=max(int(x.get("created_utc") or 0) for x in d)
  if mx<=cur:break
  cur=mx+1
  if len(d)<100:break
  time.sleep(.02)
 print(f"{sub} {y} fetched={len(out)}",flush=True);return sub,y,out
jobs=[(s,y) for s,start in SUBS for y in range(start,2027)]
rows=[];ids=set();hashes=set()
with ThreadPoolExecutor(max_workers=8) as ex:
 for fut in as_completed([ex.submit(fetch,s,y) for s,y in jobs]):
  sub,y,data=fut.result()
  for c in data:
   body=str(c.get("body") or "").strip();cid=str(c.get("id") or "")
   if len(body)<5 or body in ("[deleted]","[removed]"):continue
   h=hashlib.sha256(norm(body).encode()).hexdigest()
   if (cid and cid in ids) or h in hashes:continue
   if cid:ids.add(cid)
   hashes.add(h)
   link=str(c.get("link_id") or "").replace("t3_","")
   rows.append({"platform":"Reddit","source_type":"comment","source_url":f"https://www.reddit.com/comments/{link}/_/{cid}/" if link and cid else "",
    "date":iso(c.get("created_utc")),"rating_or_score":c.get("score"),"verified_purchase":"","helpful_vote":"","brand":"","model":"","asin":"","parent_asin":"",
    "subreddit":str(c.get("subreddit") or sub),"post_id":link,"post_title":"","comment_id":cid,"review_title":"","comment":body,"category":"待分析","dedup_key":h})
fields=list(rows[0].keys()) if rows else ["platform","source_type","source_url","date","rating_or_score","verified_purchase","helpful_vote","brand","model","asin","parent_asin","subreddit","post_id","post_title","comment_id","review_title","comment","category","dedup_key"]
with open(OUT/"reddit_pure_comments.csv","w",encoding="utf-8-sig",newline="") as f:
 w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
st={"comments_kept":len(rows),"subreddits":[x[0] for x in SUBS]}
(OUT/"stats.json").write_text(json.dumps(st,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(st),flush=True)
