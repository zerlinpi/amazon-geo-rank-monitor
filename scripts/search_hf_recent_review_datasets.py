#!/usr/bin/env python3
import requests,json,urllib.parse
queries=["amazon reviews 2025 sports outdoors asin date body","amazon reviews 2024 2025 ecommerce product reviews date","walmart reviews 2025 product reviews date","trustpilot reviews 2025 dataset","youtube comments 2025 dataset"]
for q in queries:
    print("\nQUERY",q,flush=True)
    u="https://huggingface.co/api/datasets"
    params={"search":q,"limit":100,"sort":"lastModified","direction":-1}
    r=requests.get(u,params=params,timeout=30)
    print("status",r.status_code,"url",r.url,flush=True)
    if not r.ok:
        print(r.text[:1000],flush=True); continue
    data=r.json()
    for d in data[:100]:
        print(json.dumps({
          "id":d.get("id"),"downloads":d.get("downloads"),
          "likes":d.get("likes"),"lastModified":d.get("lastModified"),
          "createdAt":d.get("createdAt"),"tags":(d.get("tags") or [])[:12]
        },ensure_ascii=False),flush=True)
