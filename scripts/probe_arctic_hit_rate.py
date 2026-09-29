#!/usr/bin/env python3
import requests, re, json, os, time
import pyarrow.parquet as pq

urls=[
 "https://huggingface.co/datasets/Dk587/arctic/resolve/main/data/comments/2026/02/000.parquet?download=true",
 "https://huggingface.co/datasets/open-index/arctic/resolve/main/data/comments/2026/02/000.parquet?download=true",
]
url=None
for u in urls:
    try:
        h=requests.head(u,allow_redirects=True,timeout=30)
        print("HEAD",u,"status",h.status_code,"final",h.url,"length",h.headers.get("content-length"),flush=True)
        if h.status_code==200:
            url=u; break
    except Exception as e:
        print("HEAD ERR",u,e,flush=True)
if not url:
    raise SystemExit("No working Arctic shard URL")

local="/tmp/arctic_2026_02_000.parquet"
print("downloading",url,flush=True)
with requests.get(url,stream=True,timeout=(30,600)) as r:
    r.raise_for_status()
    with open(local,"wb") as f:
        for chunk in r.iter_content(8*1024*1024):
            if chunk: f.write(chunk)
print("downloaded bytes",os.path.getsize(local),flush=True)

PAT_CORE=re.compile(r"walking\s*pad|walkingpad|under[-\s]?desk\s+treadmill|desk\s+treadmill|walking\s+treadmill",re.I)
PAT_BRAND=re.compile(r"urevo|deerrun|sperax|egofit|goyouth|goplus|merach|kingsmith|toputure|wellfit|maksone|vitalwalk",re.I)
CONTEXT=re.compile(r"treadmill|walking|walk|pad|desk",re.I)

pf=pq.ParquetFile(local)
count=core=brandctx=0
examples=[]
t0=time.time()
for batch in pf.iter_batches(batch_size=10000, columns=["id","author","subreddit","body","score","created_at","link_id"]):
    rows=batch.to_pylist()
    count+=len(rows)
    for row in rows:
        body=str(row.get("body") or "")
        corehit=bool(PAT_CORE.search(body))
        brandhit=bool(PAT_BRAND.search(body) and CONTEXT.search(body))
        if corehit: core+=1
        if brandhit: brandctx+=1
        if (corehit or brandhit) and len(examples)<30:
            examples.append({k:row.get(k) for k in ["id","author","subreddit","body","score","created_at","link_id"]})
print(json.dumps({
 "rows":count,"core_hits":core,"brand_context_hits":brandctx,
 "union_upper":core+brandctx,"core_rate":core/max(count,1),
 "elapsed_s":round(time.time()-t0,2),"examples":examples
},ensure_ascii=False,default=str),flush=True)
