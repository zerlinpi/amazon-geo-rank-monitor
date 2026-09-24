#!/usr/bin/env python3
import csv, json, os, re, hashlib, tempfile, shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests
import pyarrow.parquet as pq
from huggingface_hub import HfApi

TARGET = int(os.getenv("TARGET_REVIEWS", "12000"))
MIN_VALID = int(os.getenv("MIN_VALID", "10000"))
OUTDIR = Path(os.getenv("OUTDIR", "voc_output"))
OUTDIR.mkdir(parents=True, exist_ok=True)

REPO = "McAuley-Lab/Amazon-Reviews-2023"
BASE = f"https://huggingface.co/datasets/{REPO}/resolve/main"

KEYWORDS = [
    "walking pad","walkingpad","under desk treadmill","under-desk treadmill",
    "desk treadmill","walking treadmill","portable treadmill","compact treadmill",
    "foldable treadmill","folding treadmill","mini treadmill","2 in 1 treadmill",
    "2-in-1 treadmill","home office treadmill","treadmill for office",
    "treadmill under desk","walking machine"
]
BRANDS = [
    "walkingpad","kingsmith","urevo","deerrun","sperax","egofit","goyouth",
    "goplus","merach","lifespan","sunny health","toputure","maksone","wellfit",
    "axefit","motiongrey","freepi","vitalwalk"
]
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

def match_product(row):
    title = as_text(row.get("title"))
    desc = as_text(row.get("description"))
    feats = as_text(row.get("features"))
    cats = as_text(row.get("categories"))
    store = as_text(row.get("store"))
    blob = norm(" ".join([title, desc, feats, cats, store]))
    if any(k in blob for k in KEYWORDS):
        return True
    # brand + explicit compact/walking form; avoid generic full-size treadmills
    if any(b in blob for b in BRANDS) and "treadmill" in blob and any(x in blob for x in ["walking","under desk","foldable","folding","compact","portable","2 in 1","2-in-1","mini"]):
        return True
    return False

def classify(text):
    low = norm(text)
    best_cat, best_n = "其他/待聚类", 0
    for cat, pat in CATEGORY_PATTERNS.items():
        n = len(re.findall(pat, low, flags=re.I))
        if n > best_n:
            best_cat, best_n = cat, n
    return best_cat

def dedup_key(text, parent):
    return hashlib.sha256((norm(text)+"|"+str(parent)).encode("utf-8")).hexdigest()

def iso_date(ts):
    try:
        ts = int(ts)
        if ts > 10**12:
            ts /= 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    except Exception:
        return ""

def download_file(path, tmpdir):
    url = f"{BASE}/{path}?download=true"
    local = Path(tmpdir) / Path(path).name
    print(f"Downloading {path}", flush=True)
    with requests.get(url, stream=True, timeout=(30, 300), allow_redirects=True) as r:
        r.raise_for_status()
        with open(local, "wb") as f:
            for chunk in r.iter_content(chunk_size=8*1024*1024):
                if chunk:
                    f.write(chunk)
    print(f"Downloaded {local.name}: {local.stat().st_size/1024/1024:.1f} MB", flush=True)
    return local

api = HfApi()
files = api.list_repo_files(REPO, repo_type="dataset")
meta_files = sorted([p for p in files if p.startswith("raw_meta_Sports_and_Outdoors/") and p.endswith(".parquet")])
review_files = sorted([p for p in files if p.startswith("raw_review_Sports_and_Outdoors/") and p.endswith(".parquet")])
print(f"Parquet shards: metadata={len(meta_files)}, reviews={len(review_files)}", flush=True)
if not meta_files or not review_files:
    raise SystemExit("Could not find converted Sports_and_Outdoors parquet shards.")

products = {}
tmpdir = tempfile.mkdtemp(prefix="walkingpad_voc_")
try:
    # 1) metadata
    for si, path in enumerate(meta_files, 1):
        local = download_file(path, tmpdir)
        pf = pq.ParquetFile(local)
        for batch in pf.iter_batches(batch_size=5000):
            for row in batch.to_pylist():
                if match_product(row):
                    parent = str(row.get("parent_asin") or "")
                    if parent:
                        products[parent] = {
                            "parent_asin": parent,
                            "title": as_text(row.get("title")),
                            "brand": as_text(row.get("store")),
                            "rating_number": row.get("rating_number"),
                            "average_rating": row.get("average_rating"),
                            "price": row.get("price"),
                        }
        local.unlink(missing_ok=True)
        print(f"Metadata shard {si}/{len(meta_files)} complete; matched products={len(products):,}", flush=True)

    print(f"Matched products total: {len(products):,}", flush=True)
    rating_sum = sum(int(p.get("rating_number") or 0) for p in products.values())
    print(f"Matched products rating_number sum={rating_sum:,}", flush=True)

    with open(OUTDIR/"matched_products.csv","w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["parent_asin","title","brand","rating_number","average_rating","price"])
        w.writeheader(); w.writerows(products.values())

    if not products:
        raise SystemExit("No matching products found.")

    fields = [
        "platform","source_type","source_url","date","rating","verified_purchase","helpful_vote",
        "brand","model","asin","parent_asin","review_title","comment","category","dedup_key"
    ]
    raw_path = OUTDIR/"walking_pad_reviews_raw.csv"
    dedup_path = OUTDIR/"walking_pad_reviews_10k.csv"
    seen=set(); valid=[]; cats=Counter(); raw_count=0; scanned=0

    with open(raw_path,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for si, path in enumerate(review_files, 1):
            local = download_file(path, tmpdir)
            pf = pq.ParquetFile(local)
            for batch in pf.iter_batches(batch_size=10000):
                rows=batch.to_pylist(); scanned += len(rows)
                for rv in rows:
                    parent=str(rv.get("parent_asin") or "")
                    if parent not in products:
                        continue
                    text=as_text(rv.get("text")).strip()
                    if len(text)<8:
                        continue
                    title=as_text(rv.get("title"))
                    p=products[parent]
                    dk=dedup_key(text,parent)
                    row={
                        "platform":"Amazon Reviews 2023",
                        "source_type":"historical review dataset",
                        "source_url":f"https://www.amazon.com/dp/{parent}",
                        "date":iso_date(rv.get("timestamp")),
                        "rating":rv.get("rating"),
                        "verified_purchase":rv.get("verified_purchase"),
                        "helpful_vote":rv.get("helpful_vote"),
                        "brand":p["brand"],
                        "model":p["title"],
                        "asin":as_text(rv.get("asin")),
                        "parent_asin":parent,
                        "review_title":title,
                        "comment":text,
                        "category":classify(title+" "+text),
                        "dedup_key":dk,
                    }
                    w.writerow(row); raw_count += 1
                    if dk not in seen:
                        seen.add(dk); valid.append(row); cats[row["category"]]+=1
                        if len(valid)>=TARGET:
                            break
                if len(valid)>=TARGET:
                    break
            local.unlink(missing_ok=True)
            print(f"Review shard {si}/{len(review_files)}: scanned={scanned:,}, raw={raw_count:,}, dedup={len(valid):,}", flush=True)
            if len(valid)>=TARGET:
                break

    with open(dedup_path,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(valid)

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb=Workbook(); ws=wb.active; ws.title="评论明细_All"; ws.append(fields)
    for c in ws[1]:
        c.font=Font(bold=True,color="FFFFFF"); c.fill=PatternFill("solid",fgColor="121826"); c.alignment=Alignment(wrap_text=True)
    for r in valid:
        ws.append([r[h] for h in fields])
    ws.freeze_panes="A2"
    widths=[18,22,36,13,9,16,12,20,45,16,16,30,80,18,68]
    for i,wid in enumerate(widths,1): ws.column_dimensions[get_column_letter(i)].width=wid

    sw=wb.create_sheet("汇总"); sw.append(["指标","值"])
    metrics=[
        ("实际去重评论",len(valid)),("原始匹配评论",raw_count),("扫描评论总数",scanned),
        ("匹配商品数",len(products)),("匹配商品rating_number合计",rating_sum),("目标",TARGET),
        ("生成时间",datetime.now(timezone.utc).isoformat())
    ]
    for row in metrics: sw.append(list(row))
    sw.append([]); sw.append(["痛点分类","样本数"])
    for cat,n in cats.most_common(): sw.append([cat,n])
    for c in sw[1]: c.font=Font(bold=True,color="FFFFFF"); c.fill=PatternFill("solid",fgColor="121826")

    pw=wb.create_sheet("匹配商品"); pw.append(["parent_asin","title","brand","rating_number","average_rating","price"])
    for p in products.values(): pw.append([p[k] for k in ["parent_asin","title","brand","rating_number","average_rating","price"]])
    for c in pw[1]: c.font=Font(bold=True,color="FFFFFF"); c.fill=PatternFill("solid",fgColor="121826")

    xlsx=OUTDIR/"walking_pad_voc_10k.xlsx"; wb.save(xlsx)
    stats={
        "target":TARGET,"min_valid":MIN_VALID,"matched_products":len(products),"rating_number_sum":rating_sum,
        "review_shards_total":len(review_files),"reviews_scanned":scanned,"raw_matches":raw_count,
        "dedup_valid":len(valid),"categories":dict(cats)
    }
    with open(OUTDIR/"stats.json","w",encoding="utf-8") as f: json.dump(stats,f,ensure_ascii=False,indent=2)
    print(json.dumps(stats,ensure_ascii=False),flush=True)
    if len(valid)<MIN_VALID:
        print(f"WARNING: {len(valid):,} valid reviews < minimum {MIN_VALID:,}",flush=True)
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)
