#!/usr/bin/env python3
import requests, json, time
BASE="https://arctic-shift.photon-reddit.com"
tests=[
 ("tree", BASE+"/api/comments/tree", {"link_id":"t3_1ftqy0b","limit":"9999"}),
 ("linksearch", BASE+"/api/comments/search", {"link_id":"t3_1ftqy0b","sort":"asc","limit":"auto"}),
 ("postbody", BASE+"/api/posts/search", {"subreddit":"treadmills","after":"2024-09-28","before":"2026-09-29","sort":"asc","limit":"100","selftext":"walking pad"}),
]
for name,u,p in tests:
    try:
        r=requests.get(u,params=p,timeout=60,headers={"User-Agent":"walking-pad-voc-research/1.0"})
        print("\n",name,r.url,"status",r.status_code,"len",len(r.text),flush=True)
        print("headers",{k:v for k,v in r.headers.items() if "rate" in k.lower() or k.lower()=="retry-after"},flush=True)
        print(r.text[:12000],flush=True)
    except Exception as e:
        print(name,"ERR",repr(e),flush=True)
    time.sleep(2)
