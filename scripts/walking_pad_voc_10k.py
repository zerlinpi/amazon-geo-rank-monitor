#!/usr/bin/env python3
import csv, json, os, re, hashlib, gzip, io
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

TARGET = int(os.getenv("TARGET_REVIEWS", "100000"))
OUTDIR = Path(os.getenv("OUTDIR", "voc_output"))
OUTDIR.mkdir(parents=True, exist_ok=True)

META_URL = "https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw/meta_categories/meta_Sports_and_Outdoors.jsonl.gz"
REVIEWS_URL = "https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw/review_categories/Sports_and_Outdoors.jsonl.gz"

CORE_TERMS = [
    "walking pad","walkingpad","under desk treadmill","under-desk treadmill",
    "desk treadmill","walking treadmill","portable treadmill","compact treadmill",
    "foldable treadmill","folding treadmill","mini treadmill","2 in 1 treadmill",
    "2-in-1 treadmill","home office treadmill","treadmill for office",
    "treadmill under desk","walking machine"
]
CORE_BRANDS = [
    "walkingpad","kingsmith","urevo","deerrun","sperax","egofit","goyouth",
    "goplus","merach","lifespan","toputure","maksone","wellfit","axefit",
    "motiongrey","freepi","vitalwalk"
]
ACCESSORY_HINTS = [
    "treadmill mat","treadmill cover","treadmill belt replacement","replacement belt",
    "lubricant","lubrication","silicone oil","safety key","replacement key",
    "remote control replacement","replacement remote","treadmill motor","motor controller",
    "treadmill desk attachment","treadmill phone holder","treadmill book holder",
    "treadmill tablet holder","treadmill cup holder","treadmill wheel","treadmill part",
    "treadmill accessory","treadmill accessories","treadmill maintenance kit",
    "treadmill cleaner","treadmill brush"
]
NON_HUMAN_HINTS = ["dog treadmill","pet treadmill","cat treadmill","hamster treadmill","toy treadmill"]

CATEGORY_PATTERNS = {
    "安全/召回": r"recall|fire|burn|smoke|unsafe|fall|fell|injur|shock|sudden stop|abrupt stop|almost fell",
    "耐久/质量": r"fail|broke|broken|stopped working|died|motor|overheat|hot|burnt|squeak|grind|lasted",
    "跑带/稳定性": r"belt.*slip|slipping|belt.*drift|belt.*shift|center.*belt|align|wobbl|unstable|jerk",
    "噪音/振动": r"noisy|loud|noise|quiet|vibrat|stomp|downstairs|neighbor|creak",
    "尺寸/适配": r"too short|too narrow|wider|longer|stride|tall|height|width|capacity|weight limit",
    "收纳/便携": r"fold|stor(e|age)|under the bed|under bed|under sofa|under couch|upright|vertical|heavy|wheel",
    "App/遥控/数据": r"app|bluetooth|remote|disconnect|apple health|apple watch|subscription",
    "售后/保修": r"warranty|refund|return|customer service|support|replacement|parts|repair",
    "维护/跑带": r"lubricat|maintenance|clean|tension|calibrat|adjust",
    "速度/坡度/参数": r"incline|speed|mph|km/h|slows|slowing|faster",
    "人体工学/办公": r"handle|work from home|wfh|desk|meeting|zoom|typing|phone holder",
    "价格/价值": r"expensive|overpriced|price|worth|cheap|value",
    "运输/到货": r"arrived damaged|damaged|shipping|delivery|missing|box",
}

def norm(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())

def as_text(v):
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return " ".join(map(str, v))
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return str(v)

def classify_scope(row):
    title = norm(as_text(row.get("title")))
    desc = norm(as_text(row.get("description")))
    feats = norm(as_text(row.get("features")))
    cats = norm(as_text(row.get("categories")))
    store = norm(as_text(row.get("store")))
    blob = " ".join([title, desc, feats, cats, store])

    if any(x in title for x in ACCESSORY_HINTS) or any(x in title for x in NON_HUMAN_HINTS):
        return None

    # Core: explicit walking-pad / under-desk / compact walking treadmill semantics.
    if any(k in blob for k in CORE_TERMS):
        return "Core Walking Pad"

    # Core-brand + treadmill + walking/compact/foldable semantics.
    if "treadmill" in blob and any(b in blob for b in CORE_BRANDS) and any(
        q in blob for q in ["walking","under desk","under-desk","compact","portable","foldable","folding","mini","office"]
    ):
        return "Core Walking Pad"

    # Adjacent: actual human treadmill product, not accessory. Used only to expand statistical support.
    if "treadmill" in title and not any(x in title for x in ACCESSORY_HINTS + NON_HUMAN_HINTS):
        return "Adjacent Treadmill"

    return None

def classify(text):
    low = norm(text)
    best_cat, best_n = "其他/待聚类", 0
    for cat, pat in CATEGORY_PATTERNS.items():
        n = len(re.findall(pat, low, flags=re.I))
        if n > best_n:
            best_cat, best_n = cat, n
    return best_cat

def dedup_key(text, user_id):
    identity = str(user_id or "")
    base = norm(text)
    if identity:
        base = identity + "|" + base
    return hashlib.sha256(base.encode("utf-8")).hexdigest()

def iso_date(ts):
    try:
        ts = int(ts)
        if ts > 10**12:
            ts /= 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    except Exception:
        return ""

def iter_jsonl_gz(url, label):
    print(f"Streaming {label}: {url}", flush=True)
    headers = {"User-Agent":"Mozilla/5.0 walking-pad-voc-research/2.0"}
    with requests.get(url, stream=True, timeout=(30, 900), headers=headers) as r:
        r.raise_for_status()
        r.raw.decode_content = False
        with gzip.GzipFile(fileobj=r.raw, mode="rb") as gz:
            txt = io.TextIOWrapper(gz, encoding="utf-8", errors="replace")
            for line in txt:
                line=line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

# 1) Scan all product metadata and tag Core vs Adjacent.
products={}
meta_scanned=0
scope_products=Counter()
for row in iter_jsonl_gz(META_URL, "Sports & Outdoors metadata"):
    meta_scanned += 1
    scope=classify_scope(row)
    if scope:
        parent=str(row.get("parent_asin") or "")
        if parent:
            products[parent]={
                "parent_asin":parent,
                "title":as_text(row.get("title")),
                "brand":as_text(row.get("store")),
                "rating_number":row.get("rating_number"),
                "average_rating":row.get("average_rating"),
                "price":row.get("price"),
                "scope":scope
            }
            scope_products[scope]+=1
    if meta_scanned % 100000 == 0:
        print(f"metadata scanned={meta_scanned:,}; products={len(products):,}; scopes={dict(scope_products)}", flush=True)

rating_sum=sum(int(p.get("rating_number") or 0) for p in products.values())
print(f"Metadata complete: scanned={meta_scanned:,}; matched={len(products):,}; scopes={dict(scope_products)}; rating sum={rating_sum:,}", flush=True)

with open(OUTDIR/"matched_products.csv","w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=["scope","parent_asin","title","brand","rating_number","average_rating","price"])
    w.writeheader()
    for p in products.values():
        w.writerow({k:p[k] for k in ["scope","parent_asin","title","brand","rating_number","average_rating","price"]})

# 2) Scan the full review file.
# Keep every unique Core review up to TARGET; retain Adjacent candidates until we can fill to TARGET.
fields=[
    "scope","platform","source_type","source_url","date","rating","verified_purchase","helpful_vote",
    "user_id","brand","model","asin","parent_asin","review_title","comment","category","dedup_key"
]
seen=set()
core=[]
adjacent=[]
cats_core=Counter()
cats_adj=Counter()
raw_matches=Counter()
review_scanned=0

for rv in iter_jsonl_gz(REVIEWS_URL, "Sports & Outdoors reviews"):
    review_scanned += 1
    parent=str(rv.get("parent_asin") or "")
    p=products.get(parent)
    if not p:
        if review_scanned % 1000000 == 0:
            print(f"reviews scanned={review_scanned:,}; core={len(core):,}; adjacent={len(adjacent):,}", flush=True)
        continue
    text=as_text(rv.get("text")).strip()
    if len(text)<8:
        continue
    title=as_text(rv.get("title"))
    user_id=as_text(rv.get("user_id"))
    dk=dedup_key(text,user_id)
    if dk in seen:
        continue
    seen.add(dk)
    scope=p["scope"]
    row={
        "scope":scope,
        "platform":"Amazon Reviews 2023",
        "source_type":"historical review dataset",
        "source_url":f"https://www.amazon.com/dp/{parent}",
        "date":iso_date(rv.get("timestamp")),
        "rating":rv.get("rating"),
        "verified_purchase":rv.get("verified_purchase"),
        "helpful_vote":rv.get("helpful_vote"),
        "user_id":user_id,
        "brand":p["brand"],
        "model":p["title"],
        "asin":as_text(rv.get("asin")),
        "parent_asin":parent,
        "review_title":title,
        "comment":text,
        "category":classify(title+" "+text),
        "dedup_key":dk,
    }
    raw_matches[scope]+=1
    if scope=="Core Walking Pad":
        if len(core)<TARGET:
            core.append(row)
            cats_core[row["category"]]+=1
    else:
        if len(adjacent)<TARGET:
            adjacent.append(row)
            cats_adj[row["category"]]+=1

    if review_scanned % 1000000 == 0:
        print(f"reviews scanned={review_scanned:,}; core={len(core):,}; adjacent={len(adjacent):,}", flush=True)

print(f"Review scan complete: scanned={review_scanned:,}; core={len(core):,}; adjacent candidates={len(adjacent):,}", flush=True)

# Final corpus: prioritize Core completely, then fill with Adjacent to reach exactly TARGET where possible.
if len(core)>=TARGET:
    final=core[:TARGET]
else:
    need=TARGET-len(core)
    final=core + adjacent[:need]

if len(final)<TARGET:
    raise SystemExit(f"Only {len(final):,} unique reviews available; target={TARGET:,}")

final_scope=Counter(r["scope"] for r in final)
final_cats=Counter(r["category"] for r in final)

csv_path=OUTDIR/"walking_pad_reviews_100k.csv"
with open(csv_path,"w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(final)

# 3) Excel with explicit scope so the report can use Core by default.
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

xlsx=OUTDIR/"walking_pad_voc_100k.xlsx"
wb=Workbook()
ws=wb.active
ws.title="评论明细_All"
ws.append(fields)
for c in ws[1]:
    c.font=Font(bold=True,color="FFFFFF")
    c.fill=PatternFill("solid",fgColor="121826")
    c.alignment=Alignment(wrap_text=True,vertical="center")
for r in final:
    ws.append([r[h] for h in fields])
ws.freeze_panes="A2"
widths=[20,20,24,38,13,9,17,12,18,20,48,16,16,32,82,18,68]
for i,wid in enumerate(widths,1):
    ws.column_dimensions[get_column_letter(i)].width=wid

sw=wb.create_sheet("汇总")
sw.append(["指标","值"])
metrics=[
    ("最终去重评论",len(final)),
    ("Core Walking Pad",final_scope.get("Core Walking Pad",0)),
    ("Adjacent Treadmill",final_scope.get("Adjacent Treadmill",0)),
    ("扫描评论总数",review_scanned),
    ("扫描商品元数据",meta_scanned),
    ("匹配商品数",len(products)),
    ("Core商品数",scope_products.get("Core Walking Pad",0)),
    ("Adjacent商品数",scope_products.get("Adjacent Treadmill",0)),
    ("匹配商品rating_number合计",rating_sum),
    ("生成时间",datetime.now(timezone.utc).isoformat())
]
for row in metrics: sw.append(list(row))
sw.append([])
sw.append(["痛点分类","最终样本数"])
for cat,n in final_cats.most_common():
    sw.append([cat,n])
sw.append([])
sw.append(["说明","Core Walking Pad 为报告主统计；Adjacent Treadmill 只用于补充共性耐久/电机/售后证据，不应直接替代走步机专属结论。"])
for c in sw[1]:
    c.font=Font(bold=True,color="FFFFFF"); c.fill=PatternFill("solid",fgColor="121826")
sw.column_dimensions["A"].width=34; sw.column_dimensions["B"].width=80

pw=wb.create_sheet("匹配商品")
pw.append(["scope","parent_asin","title","brand","rating_number","average_rating","price"])
for p in products.values():
    pw.append([p[k] for k in ["scope","parent_asin","title","brand","rating_number","average_rating","price"]])
for c in pw[1]:
    c.font=Font(bold=True,color="FFFFFF"); c.fill=PatternFill("solid",fgColor="121826")
pw.freeze_panes="A2"
pw.column_dimensions["A"].width=22; pw.column_dimensions["B"].width=18; pw.column_dimensions["C"].width=70; pw.column_dimensions["D"].width=28

wb.save(xlsx)

stats={
    "target":TARGET,
    "meta_scanned":meta_scanned,
    "matched_products":len(products),
    "product_scopes":dict(scope_products),
    "rating_number_sum":rating_sum,
    "reviews_scanned":review_scanned,
    "unique_core_available":len(core),
    "unique_adjacent_available":len(adjacent),
    "final_rows":len(final),
    "final_scopes":dict(final_scope),
    "final_categories":dict(final_cats)
}
with open(OUTDIR/"stats_100k.json","w",encoding="utf-8") as f:
    json.dump(stats,f,ensure_ascii=False,indent=2)
print(json.dumps(stats,ensure_ascii=False),flush=True)
