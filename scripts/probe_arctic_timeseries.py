#!/usr/bin/env python3
import requests,json
BASE="https://arctic-shift.photon-reddit.com"
subs=["WalkingPads","walkingpad","treadmills","walking","StandingDesk","WorkFromHome","wfh","homeoffice","Workspaces","homegym","fitness","loseit","xxfitness","productivity","running","Exercise","desksetup","remotework","workingmoms"]
out={}
for sub in subs:
    u=BASE+"/api/time_series"
    p={"key":f"r/{sub}/comments/count","precision":"month","after":"2024-09-28","before":"2026-09-29"}
    try:
        r=requests.get(u,params=p,timeout=30)
        if r.ok:
            j=r.json(); data=j.get("data",j)
            out[sub]=data
            print(sub,"status",r.status_code,"data",json.dumps(data)[:4000],flush=True)
        else:
            print(sub,"HTTP",r.status_code,r.text[:300],flush=True)
    except Exception as e: print(sub,"ERR",e,flush=True)
print("JSON",json.dumps(out),flush=True)
