#!/usr/bin/env python3
import csv, json, os, re, hashlib, gzip, io
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import requests

TARGET = int(os.getenv("TARGET_REVIEWS", "100000"))
OUTDIR = Path(os.getenv("OUTDIR", "voc_output"))
OUTDIR.mkdir(parents=True, exist_ok=True)

BASE = "https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw"
CATEGORIES = ["Sports_and_Outdoors", "Office_Products", "Home_and_Kitchen"]

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
    if v is None: return ""
    if isinstance(v,(list,tuple)): return " ".join(map(str,v))
    if isinstance(v,dict): return json.dumps(v,ensure_ascii=False)
    return str(v)

def classify_scope(row):
    title = norm(as_text(row.get("title")))
    desc = norm(as_text(row.get("description")))
    feats = norm(as_text(row.get("features")))
    cats = norm(as_text(row.get("categories")))
    store = norm(as_text(row.get("store")))
    blob = " ".join([title,desc,feats,cats,store])

    if any(x in title for x in ACCESSORY_HINTS) or any(x in title for x in NON_HUMAN_HINTS):
        return None

    if any(k in blob for k in CORE_TERMS):
        return "Core Walking Pad"

    if "treadmill" in blob and any(b in blob for b in CORE_BRANDS) and any(
        q in blob for q in ["walking","under desk","under-desk","compact","portable","foldable","folding","mini","office"]
    ):
        return "Core Walking Pad"

    # Adjacent actual human treadmill product. Used only to fill the statistical corpus.
    if "treadmill" in title and not any(x in title for x in ACCESSORY_HINTS + NON_HUMAN_HINTS):
        return "Adjacent Treadmill"

    # Some category records omit treadmill from title but explicitly place the item in treadmill/cardio metadata.
    if "treadmill" in cats and "treadmill" in blob and not any(x in title for x in ACCESSORY_HINTS + NON_HUMAN_HINTS):
        return "Adjacent Treadmill"
    return None

def classify(text):
    low = norm(text)
    best_cat,best_n="其他/待聚类",0
    for cat,pat in CATEGORY_PATTERNS.items():
        n=len(re.findall(pat,low,flags=re.I))
        if n>best_n:
            best_cat,best_n=cat,n
    return best_cat

def dedup_key(text,user_id):
    base=norm(text)
    if user_id: base=str(user_id)+"|"+base
    return hashlib.sha256(base.encode("utf-8")).hexdigest()

def iso_date(ts):
    try:
        ts=int(ts)
        if ts>10**12: ts/=1000
        return datetime.fromtimestamp(ts,tz=timezone.utc).date().isoformat()
    except Exception:
        return ""

def iter_jsonl_gz(url,label):
    print(f"Streaming {label}: {url}",flush=True)
    headers={"User-Agent":"Mozilla/5.0 walking-pad-voc-research/3.0"}
    with requests.get(url,stream=True,timeout=(30,900),headers=headers) as r:
        r.raise_for_status()
        r.raw.decode_content=False
        with gzip.GzipFile(fileobj=r.raw,mode="rb") as gz:
            txt=io.TextIOWrapper(gz,encoding="utf-8",errors="replace")
            for line in txt:
                line=line.strip()
                if not line: continue
                try: yield json.loads(line)
                except json.JSONDecodeError: continue

fields=[
    "source_category","scope","platform","source_type","source_url","date","rating",
    "verified_purchase","helpful_vote","user_id","brand","model","asin","parent_asin",
    "review_title","comment","category","dedup_key"
]

seen=set()
core=[]
adjacent=[]
product_rows=[]
category_stats={}
global_products=0
global_meta_scanned=0
global_review_scanned=0
rating_sum_total=0

for cat_name in CATEGORIES:
    if len(core)+len(adjacent) >= TARGET:
        print(f"Target pool already reached before {cat_name}; stopping category expansion.",flush=True)
        break

    meta_url=f"{BASE}/meta_categories/meta_{cat_name}.jsonl.gz"
    review_url=f"{BASE}/review_categories/{cat_name}.jsonl.gz"

    products={}
    scope_products=Counter()
    meta_scanned=0

    for row in iter_jsonl_gz(meta_url,f"{cat_name} metadata"):
        meta_scanned+=1
        scope=classify_scope(row)
        if scope:
            parent=str(row.get("parent_asin") or "")
            if parent:
                p={
                    "source_category":cat_name,
                    "scope":scope,
                    "parent_asin":parent,
                    "title":as_text(row.get("title")),
                    "brand":as_text(row.get("store")),
                    "rating_number":row.get("rating_number"),
                    "average_rating":row.get("average_rating"),
                    "price":row.get("price")
                }
                products[parent]=p
                scope_products[scope]+=1
        if meta_scanned%100000==0:
            print(f"{cat_name} metadata scanned={meta_scanned:,}; products={len(products):,}; scopes={dict(scope_products)}",flush=True)

    cat_rating_sum=sum(int(p.get("rating_number") or 0) for p in products.values())
    global_meta_scanned += meta_scanned
    global_products += len(products)
    rating_sum_total += cat_rating_sum
    product_rows.extend(products.values())

    print(f"{cat_name} metadata complete: scanned={meta_scanned:,}; matched={len(products):,}; scopes={dict(scope_products)}",flush=True)

    review_scanned=0
    added_core=0
    added_adj=0

    for rv in iter_jsonl_gz(review_url,f"{cat_name} reviews"):
        review_scanned+=1
        parent=str(rv.get("parent_asin") or "")
        p=products.get(parent)
        if not p:
            if review_scanned%1000000==0:
                print(f"{cat_name} reviews scanned={review_scanned:,}; global core={len(core):,}; adjacent={len(adjacent):,}",flush=True)
            continue

        text=as_text(rv.get("text")).strip()
        if len(text)<8: continue
        title=as_text(rv.get("title"))
        user_id=as_text(rv.get("user_id"))
        dk=dedup_key(text,user_id)
        if dk in seen: continue
        seen.add(dk)

        row={
            "source_category":cat_name,
            "scope":p["scope"],
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
            "dedup_key":dk
        }

        if p["scope"]=="Core Walking Pad":
            if len(core)<TARGET:
                core.append(row); added_core+=1
        else:
            if len(adjacent)<TARGET:
                adjacent.append(row); added_adj+=1

        # Sports is scanned fully to establish the complete primary pool.
        # Extra categories stop immediately once the global unique pool reaches target.
        if cat_name != "Sports_and_Outdoors" and len(core)+len(adjacent) >= TARGET:
            print(f"{cat_name}: target pool reached at reviews scanned={review_scanned:,}; global pool={len(core)+len(adjacent):,}", flush=True)
            break

        if review_scanned%1000000==0:
            print(f"{cat_name} reviews scanned={review_scanned:,}; global core={len(core):,}; adjacent={len(adjacent):,}",flush=True)

    global_review_scanned += review_scanned
    category_stats[cat_name]={
        "meta_scanned":meta_scanned,
        "matched_products":len(products),
        "product_scopes":dict(scope_products),
        "rating_number_sum":cat_rating_sum,
        "reviews_scanned":review_scanned,
        "added_core":added_core,
        "added_adjacent":added_adj
    }
    print(f"{cat_name} complete. added core={added_core:,}, adjacent={added_adj:,}; global pool={len(core)+len(adjacent):,}",flush=True)

# Final: all available Core first, then Adjacent to exactly 100K.
if len(core)>=TARGET:
    final=core[:TARGET]
else:
    need=TARGET-len(core)
    final=core+adjacent[:need]

if len(final)<TARGET:
    raise SystemExit(f"Only {len(final):,} unique reviews available after categories {list(category_stats)}; target={TARGET:,}")

final_scope=Counter(r["scope"] for r in final)
final_cats=Counter(r["category"] for r in final)
final_sources=Counter(r["source_category"] for r in final)

csv_path=OUTDIR/"walking_pad_reviews_100k.csv"
with open(csv_path,"w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(final)

# XLSX
from openpyxl import Workbook
from openpyxl.styles import Font,PatternFill,Alignment
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
widths=[20,20,20,24,38,13,9,17,12,18,20,48,16,16,32,82,18,68]
for i,wid in enumerate(widths,1):
    ws.column_dimensions[get_column_letter(i)].width=wid

sw=wb.create_sheet("汇总")
sw.append(["指标","值"])
metrics=[
    ("最终去重评论",len(final)),
    ("Core Walking Pad",final_scope.get("Core Walking Pad",0)),
    ("Adjacent Treadmill",final_scope.get("Adjacent Treadmill",0)),
    ("扫描评论总数",global_review_scanned),
    ("扫描商品元数据",global_meta_scanned),
    ("匹配商品数（分类内合计）",global_products),
    ("匹配商品rating_number合计",rating_sum_total),
    ("生成时间",datetime.now(timezone.utc).isoformat())
]
for row in metrics: sw.append(list(row))
sw.append([])
sw.append(["来源分类","最终样本数"])
for k,v in final_sources.most_common(): sw.append([k,v])
sw.append([])
sw.append(["痛点分类","最终样本数"])
for k,v in final_cats.most_common(): sw.append([k,v])
sw.append([])
sw.append(["说明","Core Walking Pad 为走步机主统计；Adjacent Treadmill 仅补充共性电机、跑带、耐久、售后证据。"])
for c in sw[1]:
    c.font=Font(bold=True,color="FFFFFF"); c.fill=PatternFill("solid",fgColor="121826")
sw.column_dimensions["A"].width=36; sw.column_dimensions["B"].width=85

pw=wb.create_sheet("匹配商品")
pheaders=["source_category","scope","parent_asin","title","brand","rating_number","average_rating","price"]
pw.append(pheaders)
for p in product_rows:
    pw.append([p.get(k) for k in pheaders])
for c in pw[1]:
    c.font=Font(bold=True,color="FFFFFF"); c.fill=PatternFill("solid",fgColor="121826")
pw.freeze_panes="A2"
pw.column_dimensions["A"].width=24; pw.column_dimensions["B"].width=22; pw.column_dimensions["C"].width=18
pw.column_dimensions["D"].width=70; pw.column_dimensions["E"].width=28

wb.save(xlsx)

stats={
    "target":TARGET,
    "categories_scanned":list(category_stats),
    "category_stats":category_stats,
    "global_meta_scanned":global_meta_scanned,
    "global_review_scanned":global_review_scanned,
    "unique_core_available":len(core),
    "unique_adjacent_available":len(adjacent),
    "final_rows":len(final),
    "final_scopes":dict(final_scope),
    "final_source_categories":dict(final_sources),
    "final_categories":dict(final_cats)
}
with open(OUTDIR/"stats_100k.json","w",encoding="utf-8") as f:
    json.dump(stats,f,ensure_ascii=False,indent=2)

print(json.dumps(stats,ensure_ascii=False),flush=True)
