#!/usr/bin/env python3
from huggingface_hub import HfApi
import re, json

api=HfApi()

queries=["walking pad","treadmill reviews","reddit 2025 comments","product reviews 2025"]
for q in queries:
    print("\nQUERY",q,flush=True)
    ds=list(api.list_datasets(search=q, limit=30, full=True))
    for d in ds[:30]:
        print(d.id, "downloads=", d.downloads, "modified=", d.lastModified, "tags=", (d.tags or [])[:8], flush=True)

print("\nARCTIC FILES", flush=True)
files=api.list_repo_files("Dk587/arctic", repo_type="dataset")
months=[]
for p in files:
    if re.search(r"(comments|comment).*(2024|2025|2026)", p, re.I) or re.search(r"(2024|2025|2026).*(comments|comment)", p, re.I):
        months.append(p)
for p in months[:500]:
    print(p, flush=True)
print("matching recent comment files", len(months), flush=True)

print("\nDATAHIVE FILES", flush=True)
for repo in ["datahiveai/Amazon-Reviews-Dataset","am0507mu/Amazon-Reviews-Dataset","crawlfeeds/Trustpilot-Reviews-Dataset-20K-Sample"]:
    try:
        print(repo)
        for p in api.list_repo_files(repo, repo_type="dataset"):
            print(" ",p)
    except Exception as e:
        print("ERR",repo,e)
