#!/usr/bin/env python3
import requests,csv,json,re,time,hashlib,os
from datetime import datetime,timezone
from pathlib import Path
from collections import Counter

BASE="https://arctic-shift.photon-reddit.com"
START=datetime(2024,9,28,tzinfo=timezone.utc); END=datetime(2026,9,29,tzinfo=timezone.utc)
TARGET=int(os.getenv("TARGET_REVIEWS","200000"))
OUT=Path(os.getenv("OUTDIR","arctic_bulk_output"));OUT.mkdir(exist_ok=True)

CORE_SUBS=["WalkingPads","treadmills"]
THREAD_SUBS=["walking","StandingDesk","WorkFromHome","wfh","homeoffice","Workspaces","homegym","fitness","loseit","xxfitness","productivity","running","Exercise","desksetup","remotework","workingmoms","beginnerfitness"]
CORE_RE=re.compile(r'walking\s*pad|walkingpad|under[-\s]?desk\s+treadmill|desk\s+treadmill|walking\s+treadmill|treadmill\s+desk|urevo|deerrun|sperax|egofit|merach|kingsmith|goyouth|toputure|wellfit',re.I)
ADJ_RE=re.compile(r'compact\s+treadmill|portable\s+treadmill|slim\s+treadmill|fold(?:ing|able)?\s+treadmill|small\s+treadmill',re.I)
S=requests.Session();S.headers.update({"User-Agent":"walking-pad-voc-research/1.0"})

def months():
    cur=datetime(START.year,START.month,1,tzinfo=timezone.utc)
    while cur<END:
        nxt=datetime(cur.year+1,1,1,tzinfo=timezone.utc) if cur.month==12 else datetime(cur.year,cur.month+1,1,tzinfo=timezone.utc)
        yield max(cur,START),min(nxt,END);cur=nxt

def call(path,p,retries=6):
    for i in range(retries):
        try:
            r=S.get(BASE+path,params=p,timeout=75)
            if r.status_code==200:return r.json().get("data",[])
            if r.status_code in (422,429,500,502,503,504):
                time.sleep(min(2+i*2,12));continue
            return []
        except Exception:time.sleep(min(2+i*2,12))
    return []

def flat(data):
    out=[]
    for x in data if isinstance(data,list) else []:
        if isinstance(x,dict) and x.get("kind")=="t1" and isinstance(x.get("data"),dict):out.append(x["data"])
        elif isinstance(x,dict) and x.get("kind")!="more":out.append(x)
    return out

def paginate(path,base,a,b,max_pages=1000):
    p=dict(base)
    if "posts" in path:p.setdefault("fields","id,subreddit,created_utc,author,score,num_comments,title,selftext,permalink,url")
    else:p.setdefault("fields","id,subreddit,created_utc,author,score,body,link_id,parent_id,permalink")
    p.update({"sort":"asc","limit":"auto","before":b.isoformat().replace("+00:00","Z")})
    cur=a;prev=None
    for _ in range(max_pages):
        p["after"]=cur.isoformat().replace("+00:00","Z")
        rr=flat(call(path,p))
        if not rr:break
        yield rr
        mx=max(int(x.get("created_utc") or 0) for x in rr)
        if not mx or mx==prev:break
        prev=mx;cur=datetime.fromtimestamp(mx+1,tz=timezone.utc)
        if cur>=b or len(rr)<100:break
        time.sleep(.5)

def tier_for(text,sub,post_context=False):
    if sub.lower()=="walkingpads":return "Tier 1 - r/WalkingPads Core"
    if CORE_RE.search(text):return "Tier 1 - Walking Pad/Under-desk"
    if ADJ_RE.search(text):return "Tier 2 - Compact/Portable Treadmill"
    return "Tier 3 - General Treadmill Benchmark"

comments={};posts={};by=Counter()

def add_comment(c,tier,mode):
    cid=str(c.get("id") or "");body=str(c.get("body") or "")
    if not cid or body in ("","[deleted]","[removed]"):return
    ts=int(c.get("created_utc") or 0)
    if not START.timestamp()<=ts<END.timestamp():return
    c["_tier"]=tier;c["_mode"]=mode;comments[cid]=c;by[tier]+=1

# Phase 1: every recent comment in r/WalkingPads and r/treadmills.
for sub in CORE_SUBS:
    for a,b in months():
        for rr in paginate("/api/comments/search",{"subreddit":sub},a,b):
            for c in rr:
                add_comment(c,tier_for(str(c.get("body") or ""),sub),"whole-subreddit")
                if len(comments)>=TARGET:break
            if len(comments)>=TARGET:break
        if len(comments)>=TARGET:break
    print("whole",sub,len(comments),flush=True)
    if len(comments)>=TARGET:break

# Phase 2: find treadmill/walking-pad posts in related communities.
if len(comments)<TARGET:
    for sub in THREAD_SUBS:
        for q in ["walking pad","treadmill"]:
            for a,b in months():
                for rr in paginate("/api/posts/search",{"subreddit":sub,"query":q},a,b,max_pages=100):
                    for p in rr:
                        txt=str(p.get("title") or "")+" "+str(p.get("selftext") or "")
                        if q=="walking pad" and not CORE_RE.search(txt) and not ADJ_RE.search(txt):continue
                        p["_tier"]=tier_for(txt,sub,True)
                        posts[str(p.get("id"))]=p
            print("postscan",sub,q,"posts",len(posts),flush=True)

# Phase 3: largest threads first until target.
plist=sorted(posts.values(),key=lambda p:int(p.get("num_comments") or 0),reverse=True)
for i,p in enumerate(plist,1):
    if len(comments)>=TARGET:break
    if int(p.get("num_comments") or 0)<=0:continue
    rr=flat(call("/api/comments/tree",{
      "link_id":"t3_"+str(p["id"]),"limit":"9999",
      "fields":"id,subreddit,created_utc,author,score,body,link_id,parent_id,permalink"
    }))
    for c in rr:
        add_comment(c,p["_tier"],"relevant-post-thread")
        if len(comments)>=TARGET:break
    if i%100==0:print("trees",i,"comments",len(comments),flush=True)
    time.sleep(.35)

fields=["platform","source_type","subreddit","comment_id","link_id","parent_id","published_at","author","score","comment","source_url","relevance_tier","match_mode","dedup_key"]
with open(OUT/"reddit_recent_composite_200k.csv","w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
    for c in sorted(comments.values(),key=lambda x:int(x.get("created_utc") or 0)):
        ts=int(c.get("created_utc") or 0);cid=str(c.get("id"));body=str(c.get("body") or "");per=str(c.get("permalink") or "")
        w.writerow({"platform":"Reddit","source_type":"comment","subreddit":c.get("subreddit"),"comment_id":cid,
        "link_id":c.get("link_id"),"parent_id":c.get("parent_id"),"published_at":datetime.fromtimestamp(ts,tz=timezone.utc).isoformat(),
        "author":c.get("author"),"score":c.get("score"),"comment":body,"source_url":"https://www.reddit.com"+per if per else "",
        "relevance_tier":c.get("_tier"),"match_mode":c.get("_mode"),"dedup_key":hashlib.sha256(("reddit|"+cid+"|"+body).encode()).hexdigest()})
stats={"target":TARGET,"comments":len(comments),"matched_posts":len(posts),"tiers":dict(Counter(c.get("_tier") for c in comments.values())),
"modes":dict(Counter(c.get("_mode") for c in comments.values())),"cutoff":"2024-09-28","end":"2026-09-29"}
(OUT/"stats.json").write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(stats,ensure_ascii=False,indent=2),flush=True)
