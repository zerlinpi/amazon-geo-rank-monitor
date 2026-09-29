#!/usr/bin/env python3
import requests, csv, io, json

for owner in ["Dk587","open-index"]:
    u=f"https://huggingface.co/datasets/{owner}/arctic/resolve/main/stats.csv?download=true"
    try:
        r=requests.get(u,timeout=60)
        print("STATS",owner,"status",r.status_code,"bytes",len(r.content),flush=True)
        if r.status_code==200:
            txt=r.text
            rows=list(csv.DictReader(io.StringIO(txt)))
            comments=[x for x in rows if x.get("type")=="comments"]
            submissions=[x for x in rows if x.get("type")=="submissions"]
            comments.sort(key=lambda x:(int(x["year"]),int(x["month"])))
            submissions.sort(key=lambda x:(int(x["year"]),int(x["month"])))
            print("comment months",len(comments),"latest",comments[-20:],flush=True)
            print("submission months",len(submissions),"latest",submissions[-5:],flush=True)
            break
    except Exception as e:
        print("ERR",owner,e,flush=True)
