#!/usr/bin/env python3
import requests,re,json
from bs4 import BeautifulSoup

urls=[
 "https://www.trustpilot.com/review/deerruntreadmill.com?page=2",
 "https://www.trustpilot.com/review/walkingpad.com?page=2",
 "https://www.trustpilot.com/review/merachfit.com?page=2",
]
H={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
for u in urls:
    r=requests.get(u,headers=H,timeout=30)
    print("\nURL",u,"status",r.status_code,"len",len(r.text),"final",r.url,flush=True)
    soup=BeautifulSoup(r.text,"html.parser")
    links=[a.get("href","") for a in soup.find_all("a",href=True) if "/reviews/" in a.get("href","")]
    print("review_links",len(set(links)),"sample",list(dict.fromkeys(links))[:10],flush=True)
    # try JSON-LD review objects
    ld=[]
    for s in soup.find_all("script",{"type":"application/ld+json"}):
        try:
            j=json.loads(s.get_text())
            ld.append(j)
        except: pass
    print("jsonld blocks",len(ld),flush=True)
    txt=soup.get_text("\n",strip=True)
    print("has All reviews", "All reviews" in txt, "rated tokens", txt.count("Rated "), flush=True)
    # inspect Next data-ish script sizes
    candidates=[]
    for s in soup.find_all("script"):
        t=s.get_text()
        if "review" in t.lower() and len(t)>1000:
            candidates.append((len(t),t[:300]))
    print("script review candidates",sorted(candidates,reverse=True)[:5],flush=True)
