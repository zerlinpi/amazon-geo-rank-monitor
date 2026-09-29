#!/usr/bin/env python3
import requests,json,urllib.parse
repos=["mashu-data/reddit-comments-sample","darokiya/Reddit_Comments_Dataset","roofahmanahil4/pushshift-reddit-comments","minemaster01/Reddit-Posts-Comments-3","jebish7/Reddit-Posts-Comments-2","jebish7/Reddit-Posts-Comments","SufyanAi/Reddit_Comments_Dataset"]
for repo in repos:
    print("\n###",repo,flush=True)
    meta=requests.get(f"https://huggingface.co/api/datasets/{repo}",timeout=30)
    print("META",meta.status_code,flush=True)
    if meta.ok:
        j=meta.json()
        print("tags",(j.get("tags") or [])[:20],"lastModified",j.get("lastModified"),flush=True)
        sib=[x.get("rfilename") for x in j.get("siblings",[])][:100]
        print("files",sib,flush=True)
    # dataset server parquet metadata/config
    cfg=requests.get("https://datasets-server.huggingface.co/parquet",params={"dataset":repo},timeout=60)
    print("PARQUET",cfg.status_code, cfg.text[:3000],flush=True)
    info=requests.get("https://datasets-server.huggingface.co/info",params={"dataset":repo},timeout=60)
    print("INFO",info.status_code, info.text[:5000],flush=True)
    first=requests.get("https://datasets-server.huggingface.co/first-rows",params={"dataset":repo,"config":"default","split":"train"},timeout=60)
    print("FIRST",first.status_code, first.text[:9000],flush=True)
