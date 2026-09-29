#!/usr/bin/env python3
from datasets import load_dataset
import re, time, json

PAT = re.compile(
    r"walking\s*pad|walkingpad|under[-\s]?desk\s+treadmill|desk\s+treadmill|"
    r"urevo|deerrun|sperax|egofit|goyouth|goplus|merach|kingsmith|toputure|"
    r"wellfit|maksone|vitalwalk|walking\s+treadmill|compact\s+treadmill",
    re.I
)
N=1_000_000
print("loading stream", flush=True)
ds = load_dataset(
    "open-index/arctic",
    data_files="data/comments/2026/02/*.parquet",
    split="train",
    streaming=True,
)
count=0
hits=0
examples=[]
t0=time.time()
for row in ds:
    count += 1
    body = str(row.get("body") or "")
    if PAT.search(body):
        hits += 1
        if len(examples)<20:
            examples.append({
                "id":row.get("id"),"subreddit":row.get("subreddit"),"created_at":row.get("created_at"),
                "score":row.get("score"),"body":body[:500]
            })
    if count % 100000 == 0:
        print("scanned",count,"hits",hits,"rate",hits/count,flush=True)
    if count>=N:
        break
print(json.dumps({"scanned":count,"hits":hits,"rate":hits/max(count,1),"elapsed":time.time()-t0,"examples":examples},ensure_ascii=False,default=str),flush=True)
