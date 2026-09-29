#!/usr/bin/env python3
import requests,json
queries=["amazon reviews","amazon product reviews","walmart reviews","product reviews","ecommerce reviews","trustpilot","youtube comments","reddit comments"]
for q in queries:
    print("\nQUERY",q,flush=True)
    r=requests.get("https://huggingface.co/api/datasets",params={"search":q,"limit":100,"sort":"lastModified","direction":-1},timeout=30)
    print("status",r.status_code,flush=True)
    if not r.ok:
        print(r.text[:1000]); continue
    data=r.json()
    print("count",len(data),flush=True)
    for d in data[:100]:
        print(json.dumps({"id":d.get("id"),"downloads":d.get("downloads"),"likes":d.get("likes"),"lastModified":d.get("lastModified"),"createdAt":d.get("createdAt"),"tags":(d.get("tags") or [])[:10]},ensure_ascii=False),flush=True)
