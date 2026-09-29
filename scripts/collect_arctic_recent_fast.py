#!/usr/bin/env python3
import requests,csv,json,re,time,hashlib,os
from datetime import datetime,timezone,timedelta
from pathlib import Path
from collections import Counter

BASE="https://arctic-shift.photon-reddit.com"
START=datetime(2024,9,28,tzinfo=timezone.utc); END=datetime(2026,9,29,tzinfo=timezone.utc)
TARGET=int(os.getenv("TARGET_REVIEWS","200000"))
OUT=Path(os.getenv("OUTDIR","arctic_fast_output")); OUT.mkdir(exist_ok=True)

SUBS=[
"walkingpad","treadmills","walking","StandingDesk","WorkFromHome","wfh","homeoffice","Workspaces","homegym",
"fitness","loseit","xxfitness","productivity","running","Exercise","desksetup","remotework","workingmoms",
"beginnerfitness","orangetheory","PelotonCycle","AppleWatchFitness","GetMotivated"
]
CORE_Q='"walking pad" OR walkingpad OR "under desk treadmill" OR "desk treadmill" OR "walking treadmill" OR urevo OR deerrun OR sperax OR egofit OR merach OR kingsmith OR goyouth OR toputure OR wellfit'
CORE_RE=re.compile(r'walking\s*pad|walkingpad|under[-\s]?desk\s+treadmill|desk\s+treadmill|walking\s+treadmill|treadmill\s+desk|urevo|deerrun|sperax|egofit|merach|kingsmith|goyouth|toputure|wellfit',re.I)
ADJ_RE=re.compile(r'compact\s+treadmill|portable\s+treadmill|slim\s+treadmill|fold(?:ing|able)?\s+treadmill|small\s+treadmill',re.I)
TREAD_RE=re.compile(r'treadmill',re.I)
S=requests.Session();S.headers.update({"User-Agent":"walking-pad-voc-research/1.0"})

def months():
    cur=datetime(START.year,START.month,1,tzinfo=timezone.utc)
    while cur<END:
        nxt=datetime(cur.year+1,1,1,tzinfo=timezone.utc) if cur.month==12 else datetime(cur.year,cur.month+1,1,tzinfo=timezone.utc)
        yield max(cur,START),min(nxt,END)
        cur=nxt

def call(path,params,retries=5):
    for i in range(retries):
        try:
            r=S.get(BASE+path,params=params,timeout=75)
            if r.status_code==200:return r.json().get("data",[])
            if r.status_code in (422,429,500,502,503,504):
                time.sleep(min(2+i*2,10));continue
            return []
        except Exception:time.sleep(min(2+i*2,10))
    return []

def rows(data):
    o=[]
    for x in data if isinstance(data,list) else []:
        if isinstance(x,dict) and x.get("kind")=="t1" and isinstance(x.get("data"),dict):o.append(x["data"])
        elif isinstance(x,dict):o.append(x)
    return o

def search(path,base,a,b,max_pages=30):
    p=dict(base)
    p["fields"]="id,subreddit,created_utc,author,score,num_comments,title,selftext,permalink,url" if "posts" in path else "id,subreddit,created_utc,author,score,body,link_id,parent_id,permalink"
    p.update({"sort":"asc","limit":"auto","before":b.isoformat().replace("+00:00","Z")})
    cursor=a;last=None
    for _ in range(max_pages):
        p["after"]=cursor.isoformat().replace("+00:00","Z")
        rr=rows(call(path,p))
        if not rr:break
        yield rr
        mx=max(int(x.get("created_utc") or 0) for x in rr)
        if not mx or mx==last:break
        last=mx;cursor=datetime.fromtimestamp(mx+1,tz=timezone.utc)
        if cursor>=b or len(rr)<100:break
        time.sleep(.35)

def tier(text):
    if CORE_RE.search(text):return "Tier 1 - Walking Pad/Under-desk"
    if ADJ_RE.search(text):return "Tier 2 - Compact/Portable Treadmill"
    if TREAD_RE.search(text):return "Tier 3 - General Treadmill Benchmark"
    return None

comments={};posts={};stat=Counter()

def addc(c,t,mode):
    cid=str(c.get("id") or "");body=str(c.get("body") or "")
    if not cid or body in ("","[deleted]","[removed]"):return
    ts=int(c.get("created_utc") or 0)
    if not START.timestamp()<=ts<END.timestamp():return
    c["_tier"]=t;c["_mode"]=mode;comments[cid]=c;stat[t]+=1

# Direct comment search. Core query first; then general treadmill for benchmark.
for sub in SUBS:
    for a,b in months():
        for rr in search("/api/comments/search",{"subreddit":sub,"body":CORE_Q},a,b,max_pages=20):
            for c in rr:
                t=tier(str(c.get("body") or ""))
                if t:addc(c,t,"direct-core")
        if len(comments)>=TARGET:break
    print("direct core",sub,len(comments),flush=True)
    if len(comments)>=TARGET:break

if len(comments)<TARGET:
    for sub in SUBS:
        for a,b in months():
            for rr in search("/api/comments/search",{"subreddit":sub,"body":"treadmill"},a,b,max_pages=50):
                for c in rr:
                    t=tier(str(c.get("body") or ""))
                    if t:addc(c,t,"direct-treadmill")
                    if len(comments)>=TARGET:break
                if len(comments)>=TARGET:break
            if len(comments)>=TARGET:break
        print("direct treadmill",sub,len(comments),flush=True)
        if len(comments)>=TARGET:break

# Find relevant posts (core and treadmill) and expand their entire comment trees.
if len(comments)<TARGET:
    for sub in SUBS:
        queries=[(CORE_Q,"core-post"),("treadmill","treadmill-post")]
        for q,mode in queries:
            for a,b in months():
                for rr in search("/api/posts/search",{"subreddit":sub,"query":q},a,b,max_pages=30):
                    for p in rr:
                        txt=(str(p.get("title") or "")+" "+str(p.get("selftext") or ""))
                        t=tier(txt)
                        if not t:continue
                        p["_tier"]=t
                        posts[str(p.get("id"))]=p
            print("posts",sub,mode,len(posts),flush=True)

# Prioritize posts with more comments.
if len(comments)<TARGET:
    plist=sorted(posts.values(),key=lambda p:int(p.get("num_comments") or 0),reverse=True)
    for i,p in enumerate(plist,1):
        if int(p.get("num_comments") or 0)<=0:continue
        data=rows(call("/api/comments/tree",{
            "link_id":"t3_"+str(p["id"]),"limit":"9999",
            "fields":"id,subreddit,created_utc,author,score,body,link_id,parent_id,permalink"
        }))
        for c in data:
            addc(c,p["_tier"],"thread")
            if len(comments)>=TARGET:break
        if i%100==0:print("trees",i,"comments",len(comments),flush=True)
        if len(comments)>=TARGET:break
        time.sleep(.25)

fields=["platform","source_type","subreddit","comment_id","link_id","parent_id","published_at","author","score","comment","source_url","relevance_tier","match_mode","dedup_key"]
with open(OUT/"reddit_recent_200k.csv","w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
    for c in sorted(comments.values(),key=lambda x:int(x.get("created_utc") or 0)):
        ts=int(c.get("created_utc") or 0);body=str(c.get("body") or "");cid=str(c.get("id"))
        per=str(c.get("permalink") or "")
        w.writerow({"platform":"Reddit","source_type":"comment","subreddit":c.get("subreddit"),"comment_id":cid,
        "link_id":c.get("link_id"),"parent_id":c.get("parent_id"),"published_at":datetime.fromtimestamp(ts,tz=timezone.utc).isoformat(),
        "author":c.get("author"),"score":c.get("score"),"comment":body,
        "source_url":"https://www.reddit.com"+per if per else "","relevance_tier":c.get("_tier"),"match_mode":c.get("_mode"),
        "dedup_key":hashlib.sha256(("reddit|"+cid+"|"+body).encode()).hexdigest()})
stats={"target":TARGET,"comments":len(comments),"posts":len(posts),"tiers":dict(Counter(c.get("_tier") for c in comments.values())),
"modes":dict(Counter(c.get("_mode") for c in comments.values())),"cutoff":"2024-09-28","end":"2026-09-29"}
(OUT/"stats.json").write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(stats,ensure_ascii=False,indent=2),flush=True)
