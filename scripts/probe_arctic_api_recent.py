#!/usr/bin/env python3
import requests, json, urllib.parse, time
BASE="https://arctic-shift.photon-reddit.com"
tests=[
  ("/api/comments/search", {"subreddit":"treadmills","after":"2024-09-28","before":"2026-09-29","sort":"asc","limit":"100","body":"walking pad"}),
  ("/api/comments/search", {"subreddit":"StandingDesk","after":"2024-09-28","before":"2026-09-29","sort":"asc","limit":"100","body":"walking pad"}),
  ("/api/comments/search", {"subreddit":"walking","after":"2024-09-28","before":"2026-09-29","sort":"asc","limit":"100","body":"walking pad"}),
  ("/api/posts/search", {"subreddit":"treadmills","after":"2024-09-28","before":"2026-09-29","sort":"asc","limit":"100","title":"walking pad"}),
  ("/api/posts/search", {"subreddit":"StandingDesk","after":"2024-09-28","before":"2026-09-29","sort":"asc","limit":"100","title":"walking pad"}),
]
for path,params in tests:
    url=BASE+path
    try:
        r=requests.get(url,params=params,timeout=60,headers={"User-Agent":"walking-pad-voc-research/1.0"})
        print("\nTEST",r.url,flush=True)
        print("status",r.status_code,"len",len(r.text),flush=True)
        print("headers", {k:v for k,v in r.headers.items() if "rate" in k.lower() or k.lower() in ("content-type","retry-after")}, flush=True)
        if r.ok:
            j=r.json()
            data=j.get("data",j) if isinstance(j,dict) else j
            if isinstance(data,dict):
                # handle possible nested arrays
                arr=None
                for k in ("data","comments","posts","results"):
                    if isinstance(data.get(k),list):
                        arr=data[k]; break
                if arr is None:
                    arr=[]
            elif isinstance(data,list):
                arr=data
            else:
                arr=[]
            print("top keys", list(j.keys()) if isinstance(j,dict) else type(j), "rows", len(arr), flush=True)
            print("sample", json.dumps(arr[:3],ensure_ascii=False)[:6000], flush=True)
            if arr:
                print("first_created",arr[0].get("created_utc"),"last_created",arr[-1].get("created_utc"),flush=True)
        else:
            print(r.text[:5000],flush=True)
    except Exception as e:
        print("ERR",repr(e),flush=True)
    time.sleep(1)
