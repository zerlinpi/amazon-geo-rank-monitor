#!/usr/bin/env python3
import requests, csv, json, re, time, hashlib, os
from datetime import datetime, timezone
from calendar import monthrange
from pathlib import Path
from collections import Counter

BASE="https://arctic-shift.photon-reddit.com"
START=datetime(2024,9,28,tzinfo=timezone.utc)
END=datetime(2026,9,29,tzinfo=timezone.utc)
TARGET=int(os.getenv("TARGET_REVIEWS","200000"))
OUT=Path(os.getenv("OUTDIR","arctic_recent_output")); OUT.mkdir(exist_ok=True)

FULL_SUBS=[
    "walkingpad","treadmills","walking","StandingDesk","WorkFromHome",
    "wfh","homeoffice","Workspaces","homegym"
]
BROAD_SUBS=[
    "fitness","loseit","xxfitness","productivity","running","Exercise",
    "office","desksetup","remotework","workingmoms"
]

CORE_RE=re.compile(
    r"\bwalking\s*pad\b|\bwalkingpad\b|\bunder[-\s]?desk\s+treadmill\b|"
    r"\bdesk\s+treadmill\b|\bwalking\s+treadmill\b|\btreadmill\s+desk\b|"
    r"\boffice\s+treadmill\b",
    re.I
)
BRAND_RE=re.compile(
    r"\burevo\b|\bdeer\s*run\b|\bdeerrun\b|\bsperax\b|\begofit\b|"
    r"\bwalkingpad\b|\bkingsmith\b|\bmerach\b|\bgoplus\b|\bgo\s*youth\b|"
    r"\bgoyouth\b|\btoputure\b|\bwellfit\b|\blifespan\b|\bmaksone\b|"
    r"\bvitalwalk\b|\bfreepi\b|\btreaflow\b|\bmotiongrey\b",
    re.I
)
ADJ_RE=re.compile(
    r"\bcompact\s+treadmill\b|\bportable\s+treadmill\b|\bslim\s+treadmill\b|"
    r"\bfold(?:ing|able)?\s+treadmill\b|\bsmall\s+treadmill\b",
    re.I
)
CONTEXT_RE=re.compile(r"treadmill|walking|walk|pad|desk|office|steps",re.I)

KEYWORDS=[
 "walking pad","walkingpad","under desk treadmill","desk treadmill","walking treadmill",
 "urevo","deerrun","sperax","egofit","merach","kingsmith","goplus","goyouth",
 "toputure","wellfit","lifespan"
]

session=requests.Session()
session.headers.update({"User-Agent":"walking-pad-voc-research/1.0 (+public archive analysis)"})

def month_windows(start,end):
    cur=datetime(start.year,start.month,1,tzinfo=timezone.utc)
    while cur<end:
        y,m=cur.year,cur.month
        if m==12: nxt=datetime(y+1,1,1,tzinfo=timezone.utc)
        else: nxt=datetime(y,m+1,1,tzinfo=timezone.utc)
        a=max(cur,start); b=min(nxt,end)
        if a<b: yield a,b
        cur=nxt

def api(path,params,retries=6):
    last=None
    for attempt in range(retries):
        try:
            r=session.get(BASE+path,params=params,timeout=75)
            last=r
            if r.status_code==200:
                j=r.json()
                return j.get("data",j)
            if r.status_code in (422,429,500,502,503,504):
                time.sleep(min(2+attempt*2,12)); continue
            print("HTTP",r.status_code,r.url,r.text[:300],flush=True)
            return []
        except Exception as e:
            print("ERR",path,params,type(e).__name__,str(e)[:200],flush=True)
            time.sleep(min(2+attempt*2,12))
    if last is not None:
        print("GIVEUP",last.status_code,last.url,last.text[:300],flush=True)
    return []

def normalize_rows(data):
    if not isinstance(data,list): return []
    out=[]
    for x in data:
        if isinstance(x,dict) and x.get("kind")=="t1" and isinstance(x.get("data"),dict):
            out.append(x["data"])
        elif isinstance(x,dict):
            out.append(x)
    return out

def paginate(path,base_params,a,b,max_pages=500):
    params=dict(base_params)
    if "posts" in path:
        params.setdefault("fields","id,subreddit,created_utc,author,score,num_comments,title,selftext,permalink,url")
    else:
        params.setdefault("fields","id,subreddit,created_utc,author,score,body,link_id,parent_id,permalink")
    params.update({"after":a.isoformat().replace("+00:00","Z"),"before":b.isoformat().replace("+00:00","Z"),"sort":"asc","limit":"auto"})
    cursor=a
    seen_last=None
    for page in range(max_pages):
        params["after"]=cursor.isoformat().replace("+00:00","Z")
        rows=normalize_rows(api(path,params))
        if not rows: break
        yield rows
        ts=[int(x.get("created_utc") or x.get("created") or 0) for x in rows]
        last=max(ts) if ts else 0
        if not last or last==seen_last: break
        seen_last=last
        cursor=datetime.fromtimestamp(last+1,tz=timezone.utc)
        if cursor>=b: break
        if len(rows)<100: break
        time.sleep(0.25)

def rel_tier(text,sub):
    if CORE_RE.search(text): return "Tier 1 - Explicit Walking Pad/Under-desk"
    if BRAND_RE.search(text) and CONTEXT_RE.search(text): return "Tier 1 - Walking Pad Brand Context"
    if ADJ_RE.search(text): return "Tier 2 - Compact/Portable Treadmill"
    if sub.lower()=="walkingpad": return "Tier 1 - r/walkingpad Context"
    return None

# 1) Find relevant posts in focused subreddits and all direct keyword posts in broad subreddits.
posts={}
post_stats=Counter()

print("PHASE 1 posts",flush=True)
for sub in FULL_SUBS:
    for a,b in month_windows(START,END):
        for rows in paginate("/api/posts/search",{"subreddit":sub},a,b):
            for p in rows:
                text=(str(p.get("title") or "")+"\n"+str(p.get("selftext") or ""))
                tier=rel_tier(text,sub)
                if tier:
                    p["_tier"]=tier
                    posts[p.get("id")]=p
                    post_stats[sub]+=1
        if len(posts)>=TARGET: break
    print("posts",sub,post_stats[sub],"total",len(posts),flush=True)

# Broad subreddits: keyword-search title only, monthly to avoid timeout.
for sub in BROAD_SUBS:
    for kw in KEYWORDS[:5]:
        for a,b in month_windows(START,END):
            params={"subreddit":sub,"title":kw}
            for rows in paginate("/api/posts/search",params,a,b,max_pages=30):
                for p in rows:
                    text=(str(p.get("title") or "")+"\n"+str(p.get("selftext") or ""))
                    tier=rel_tier(text,sub)
                    if tier:
                        p["_tier"]=tier
                        posts[p.get("id")]=p
                        post_stats[sub]+=1
    print("posts broad",sub,post_stats[sub],"total",len(posts),flush=True)

# Save posts
post_fields=["id","subreddit","created_utc","author","score","num_comments","title","selftext","permalink","url","_tier"]
with open(OUT/"reddit_recent_posts.csv","w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=post_fields,extrasaction="ignore");w.writeheader()
    for p in sorted(posts.values(),key=lambda x:int(x.get("created_utc") or 0)):
        w.writerow(p)

# 2) Collect all comments in focused subs, retaining comments whose link_id is a matched post OR whose body itself is directly relevant.
comments={}
comment_stats=Counter()
matched_links={"t3_"+pid for pid in posts}
print("PHASE 2 comments full subs",len(matched_links),"matched links",flush=True)

def keep_comment(c,sub):
    body=str(c.get("body") or "")
    lid=str(c.get("link_id") or "")
    if lid in matched_links:
        pid=lid[3:] if lid.startswith("t3_") else lid
        ptier=(posts.get(pid) or {}).get("_tier")
        return ptier or "Tier 1 - Relevant Post Thread"
    return rel_tier(body,sub)

for sub in FULL_SUBS:
    for a,b in month_windows(START,END):
        for rows in paginate("/api/comments/search",{"subreddit":sub},a,b,max_pages=1000):
            for c in rows:
                created=int(c.get("created_utc") or c.get("created") or 0)
                if not (START.timestamp() <= created < END.timestamp()): continue
                body=str(c.get("body") or "")
                if body in ("[deleted]","[removed]",""): continue
                tier=keep_comment(c,sub)
                if not tier: continue
                cid=str(c.get("id") or "")
                if not cid: continue
                c["_tier"]=tier
                c["_match_mode"]="thread" if str(c.get("link_id") or "") in matched_links else "body"
                comments[cid]=c
                comment_stats[sub]+=1
                if len(comments)>=TARGET: break
            if len(comments)>=TARGET: break
        if len(comments)>=TARGET: break
    print("comments",sub,comment_stats[sub],"unique",len(comments),flush=True)
    if len(comments)>=TARGET: break

# 3) Direct keyword comment searches in broader subs; only text-matched comments.
if len(comments)<TARGET:
    print("PHASE 3 broad direct keyword comments",flush=True)
    for sub in BROAD_SUBS:
        for kw in KEYWORDS:
            for a,b in month_windows(START,END):
                for rows in paginate("/api/comments/search",{"subreddit":sub,"body":kw},a,b,max_pages=50):
                    for c in rows:
                        created=int(c.get("created_utc") or c.get("created") or 0)
                        if not (START.timestamp() <= created < END.timestamp()): continue
                        body=str(c.get("body") or "")
                        if body in ("[deleted]","[removed]",""): continue
                        tier=rel_tier(body,sub)
                        if not tier: continue
                        cid=str(c.get("id") or "")
                        if not cid: continue
                        c["_tier"]=tier;c["_match_mode"]="body"
                        comments[cid]=c;comment_stats[sub]+=1
                        if len(comments)>=TARGET: break
                    if len(comments)>=TARGET: break
                if len(comments)>=TARGET: break
            if len(comments)>=TARGET: break
        print("comments broad",sub,comment_stats[sub],"unique",len(comments),flush=True)
        if len(comments)>=TARGET: break

# 4) If matched broad-sub posts exist, fetch comment trees for them (bounded, retry). This captures replies that don't repeat keywords.
if len(comments)<TARGET:
    print("PHASE 4 broad post trees",flush=True)
    broad_set={s.lower() for s in BROAD_SUBS}
    tree_posts=[p for p in posts.values() if str(p.get("subreddit") or "").lower() in broad_set]
    for idx,p in enumerate(tree_posts,1):
        pid=str(p.get("id"))
        data=normalize_rows(api("/api/comments/tree",{"link_id":"t3_"+pid,"limit":"9999","fields":"id,subreddit,created_utc,author,score,body,link_id,parent_id,permalink"}))
        for c in data:
            created=int(c.get("created_utc") or c.get("created") or 0)
            if not (START.timestamp() <= created < END.timestamp()): continue
            body=str(c.get("body") or "")
            if body in ("[deleted]","[removed]",""): continue
            cid=str(c.get("id") or "")
            if not cid: continue
            c["_tier"]=p.get("_tier") or "Tier 1 - Relevant Post Thread"
            c["_match_mode"]="thread"
            comments[cid]=c
            if len(comments)>=TARGET: break
        if idx%100==0: print("trees",idx,"unique comments",len(comments),flush=True)
        if len(comments)>=TARGET: break
        time.sleep(0.2)

# Export comments
fields=["platform","source_type","subreddit","comment_id","link_id","parent_id","published_at","author","score","comment","source_url","relevance_tier","match_mode","dedup_key"]
with open(OUT/"reddit_recent_comments.csv","w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
    for c in sorted(comments.values(),key=lambda x:int(x.get("created_utc") or 0)):
        ts=int(c.get("created_utc") or c.get("created") or 0)
        dt=datetime.fromtimestamp(ts,tz=timezone.utc).isoformat()
        permalink=str(c.get("permalink") or "")
        body=str(c.get("body") or "")
        cid=str(c.get("id") or "")
        w.writerow({
            "platform":"Reddit","source_type":"comment","subreddit":c.get("subreddit"),
            "comment_id":cid,"link_id":c.get("link_id"),"parent_id":c.get("parent_id"),
            "published_at":dt,"author":c.get("author"),"score":c.get("score"),
            "comment":body,"source_url":"https://www.reddit.com"+permalink if permalink else "",
            "relevance_tier":c.get("_tier"),"match_mode":c.get("_match_mode"),
            "dedup_key":hashlib.sha256(("reddit|"+cid+"|"+body).encode()).hexdigest()
        })

dates=[int(c.get("created_utc") or c.get("created") or 0) for c in comments.values()]
stats={
    "target":TARGET,"comments":len(comments),"matched_posts":len(posts),
    "date_cutoff":"2024-09-28","date_end_exclusive":"2026-09-29",
    "min_date":datetime.fromtimestamp(min(dates),tz=timezone.utc).isoformat() if dates else None,
    "max_date":datetime.fromtimestamp(max(dates),tz=timezone.utc).isoformat() if dates else None,
    "comments_by_subreddit":dict(comment_stats),
    "posts_by_subreddit":dict(post_stats),
    "tier_counts":dict(Counter(c.get("_tier") for c in comments.values())),
    "match_modes":dict(Counter(c.get("_match_mode") for c in comments.values()))
}
(OUT/"stats.json").write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(stats,ensure_ascii=False,indent=2),flush=True)
