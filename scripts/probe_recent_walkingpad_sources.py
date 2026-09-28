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
