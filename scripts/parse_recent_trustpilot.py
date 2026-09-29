#!/usr/bin/env python3
import json,re,csv,hashlib
from pathlib import Path
from datetime import datetime, timezone
from dateutil import parser as dtparser

ROOT=Path(".")
RAW=ROOT/"tmp_voc_raw"
OUT=Path("recent_voc_output")
OUT.mkdir(exist_ok=True)
CUTOFF=datetime(2024,9,28,tzinfo=timezone.utc)

rating_re=re.compile(r"Rated\s+(\d)\s+out of 5 stars",re.I)
title_re=re.compile(r"\[\*\*(.*?)\*\*\]\((https://www\.trustpilot\.com/reviews/([A-Za-z0-9]+))\)")
date_re=re.compile(r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+20\d{2}$")
relative_re=re.compile(r"^(\d+\s+(minute|hour|day|week|month)s? ago|Yesterday)$",re.I)
reply_re=re.compile(r"^Reply from ",re.I)

core_terms=re.compile(r"walking\s*pad|walkingpad|walking\s*path|under[-\s]?desk\s+treadmill|desk\s+treadmill|walking\s+treadmill|treadmill",re.I)
service_terms=re.compile(r"customer service|support|refund|replacement|warranty|shipping|delivery|order|return|email|reply|response|contact",re.I)
product_issue_terms=re.compile(r"motor|belt|noise|noisy|quiet|remote|app|bluetooth|speed|incline|fold|compact|heavy|wheel|heat|overheat|stop|stopped|error|code|break|broke|broken|slip|drift|shock|static|burn|smoke|safety|fall|wobble",re.I)

def parse_page(md, brand, domain, page):
    lines=[x.strip() for x in md.splitlines()]
    out=[]
    i=0
    while i < len(lines):
        m=rating_re.search(lines[i])
        if not m:
            i+=1; continue
        rating=int(m.group(1))
        j=i+1
        # skip blanks/redirected until title review link
        while j < len(lines) and j < i+12:
            tm=title_re.search(lines[j])
            if tm: break
            j+=1
        if j>=len(lines) or not title_re.search(lines[j]):
            i+=1; continue
        tm=title_re.search(lines[j])
        title=re.sub(r"\\","",tm.group(1)).strip()
        url=tm.group(2); rid=tm.group(3)
        body_lines=[]
        k=j+1
        exact_date=None
        while k < len(lines) and k < j+80:
            line=lines[k]
            if date_re.match(line):
                exact_date=line
                break
            # Stop if another rating appears before a date (malformed card)
            if rating_re.search(line) and k>j+1:
                break
            if line and not relative_re.match(line) and line not in {"Redirected","Unprompted review","Verified review","Useful","Share","Advertisement"}:
                body_lines.append(line)
            k+=1
        if not exact_date:
            i=j+1; continue
        try:
            dt=dtparser.parse(exact_date).replace(tzinfo=timezone.utc)
        except Exception:
            i=k+1; continue
        if dt < CUTOFF:
            i=k+1; continue
        body="\n".join(body_lines).strip()
        if not body:
            body=title
        blob=f"{title} {body}"
        explicit=bool(core_terms.search(blob))
        service=bool(service_terms.search(blob))
        product_issue=bool(product_issue_terms.search(blob))
        voc_type="Product VOC" if explicit or product_issue else ("Service VOC" if service else "Brand/Experience VOC")
        relevance="Tier 1 - Explicit Walking Pad/Treadmill" if explicit else "Tier 2 - Brand-context recent review"
        dedup=hashlib.sha256((rid+"|"+body.lower().strip()).encode("utf-8")).hexdigest()
        out.append({
            "platform":"Trustpilot","brand":brand,"domain":domain,"page":page,
            "review_id":rid,"review_url":url,"published_at":dt.date().isoformat(),
            "rating":rating,"title":title,"comment":body,"voc_type":voc_type,
            "relevance_tier":relevance,"explicit_walkingpad":1 if explicit else 0,
            "product_issue_signal":1 if product_issue else 0,
            "service_signal":1 if service else 0,"dedup_key":dedup
        })
        i=k+1
    return out

rows=[]
for fp in sorted(RAW.glob("trustpilot_*.json")):
    try:
        obj=json.loads(fp.read_text(encoding="utf-8"))
    except Exception as e:
        print("skip bad json",fp,e); continue
    brand=obj.get("brand",""); domain=obj.get("domain","")
    for p in obj.get("pages",[]):
        md=p.get("markdown","")
        if len(md)<3000 or "Log in or sign up below" in md:
            continue
        rows.extend(parse_page(md,brand,domain,p.get("page")))

# dedup review ID, prefer explicit / longer body
best={}
for r in rows:
    old=best.get(r["review_id"])
    if old is None or (r["explicit_walkingpad"],len(r["comment"])) > (old["explicit_walkingpad"],len(old["comment"])):
        best[r["review_id"]]=r
rows=list(best.values())
rows.sort(key=lambda r:(r["published_at"],r["brand"],r["review_id"]),reverse=True)

fields=["platform","brand","domain","page","review_id","review_url","published_at","rating","title","comment","voc_type","relevance_tier","explicit_walkingpad","product_issue_signal","service_signal","dedup_key"]
with open(OUT/"trustpilot_recent_reviews.csv","w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

from collections import Counter
stats={
 "cutoff":"2024-09-28",
 "rows":len(rows),
 "explicit_walkingpad":sum(r["explicit_walkingpad"] for r in rows),
 "product_voc":sum(r["voc_type"]=="Product VOC" for r in rows),
 "service_voc":sum(r["voc_type"]=="Service VOC" for r in rows),
 "by_brand":dict(Counter(r["brand"] for r in rows)),
 "by_rating":dict(Counter(str(r["rating"]) for r in rows)),
 "min_date":min((r["published_at"] for r in rows),default=None),
 "max_date":max((r["published_at"] for r in rows),default=None),
}
(OUT/"stats.json").write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(stats,ensure_ascii=False,indent=2))
