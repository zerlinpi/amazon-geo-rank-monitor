#!/usr/bin/env python3
import requests,re,json
from bs4 import BeautifulSoup

UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
urls=[
 "https://www.walmart.com/search?q=walking+pad",
 "https://www.walmart.com/ip/19187419246",
]
for url in urls:
    print("\nURL",url,flush=True)
    r=requests.get(url,headers=UA,timeout=30)
    print("status",r.status_code,"len",len(r.text),"final",r.url,flush=True)
    print(r.text[:500].replace("\n"," "),flush=True)
    print("product urls",len(set(re.findall(r'https?://www\\.walmart\\.com/ip/[^"\\s?]+',r.text))),flush=True)
    print("review tokens",len(re.findall(r'customer reviews|reviewText|reviewId|rating',r.text,re.I)),flush=True)
    m=re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',r.text,re.S)
    print("next_data",bool(m), "chars", len(m.group(1)) if m else 0, flush=True)
    if m:
        try:
            data=json.loads(m.group(1))
            print("next keys",list(data.keys()),flush=True)
        except Exception as e: print("json error",e,flush=True)


print("\n=== REDDIT PROBE ===", flush=True)
for url in [
 "https://www.reddit.com/search.json?q=walking%20pad&sort=new&t=year&limit=100&raw_json=1",
 "https://old.reddit.com/r/walking/search.json?q=walking%20pad&restrict_sr=1&sort=new&t=year&limit=100&raw_json=1"
]:
    try:
        rr=requests.get(url,headers={"User-Agent":"walking-pad-voc-research/1.0"},timeout=30)
        print("reddit",url,"status",rr.status_code,"len",len(rr.text),flush=True)
        if rr.status_code==200:
            jj=rr.json()
            ch=jj.get("data",{}).get("children",[])
            print("children",len(ch),"first",[(x.get("data",{}).get("id"),x.get("data",{}).get("num_comments"),x.get("data",{}).get("created_utc")) for x in ch[:5]],flush=True)
    except Exception as e: print("reddit error",e,flush=True)
