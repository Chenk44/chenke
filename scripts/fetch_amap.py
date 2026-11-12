"""从高德开放平台拉候选地点，输出成待人工标注的 CSV。

设计原则：
1. **不覆盖 data/pois_shenzhen.csv**。人工标注过的那 49 条是心血，脚本只往
   ``data/amap_candidates.csv`` 里写候选，由人挑、人补字段。
2. **商圈中心从现有数据算**，而不是我手填坐标——手填坐标错一个数，整个商圈
   的候选就跑到别的地方去了。
3. **按 typecode 分类，不按关键词分类**。实测「剧本杀」的搜索结果第一条是咖啡厅
   （typecode 050500），关键词只能用来触发检索，不能用来定性。
4. 响应缓存到 .tmp/amap_cache/，同一个查询重跑不消耗配额。

用法::

    python -m scripts.fetch_amap              # 拉取，写入 data/amap_candidates.csv
    python -m scripts.fetch_amap --dry-run    # 只打印计划，不发请求
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from app.config import settings  # noqa: E402

BASE = "https://restapi.amap.com/v3"
CSV_IN = ROOT / "data" / "pois_shenzhen.csv"
CSV_OUT = ROOT / "data" / "amap_candidates.csv"
CACHE = ROOT / ".tmp" / "amap_cache"

# 关键词 → (检索半径米, 该关键词期望落到的品类)。品类只是「期望」，
# 最终以返回的 typecode 为准（见 CATEGORY_BY_TYPECODE）。
QUERIES: list[tuple[str, int]] = [
    ("购物中心", 2500),
    ("公园", 2500),
    ("美食", 1200),
    ("咖啡", 1200),
    ("电影院", 2000),
    ("密室逃脱", 2000),
    ("剧本杀", 2000),
    ("书店", 2000),
    ("羽毛球馆", 2500),
    ("攀岩", 2500),
    ("沙滩", 3000),
    ("博物馆", 3000),
    ("美术馆", 3000),
    ("夜市", 2500),
]

# 高德 typecode 前 4 位 → 我们用的大类。顺序有意义，先匹配到的赢。
CATEGORY_BY_TYPECODE: list[tuple[str, str]] = [
    ("0501", "餐饮"),
    ("0502", "餐饮"),
    ("0503", "餐饮"),
    ("0504", "餐饮"),
    ("0505", "咖啡"),
    ("0601", "玩乐"),  # 商场/购物中心
    ("0610", "市集"),
    ("0612", "书店"),
    ("06", "玩乐"),
    ("0801", "运动"),
    ("0803", "玩乐"),  # KTV / 密室 / 桌游
    ("0805", "玩乐"),
    ("0806", "影院"),
    ("080", "玩乐"),
    ("1101", "公园"),
    ("1102", "公园"),
    ("11", "公园"),
    ("1401", "展览"),
    ("1402", "展览"),
    ("1403", "展览"),
    ("1405", "展览"),
    ("1406", "展览"),
    ("14", "展览"),
]


def category_of(typecode: str) -> str:
    for prefix, cat in CATEGORY_BY_TYPECODE:
        if typecode.startswith(prefix):
            return cat
    return ""


def area_centers() -> dict[str, tuple[float, float]]:
    """从现有 CSV 求每个商圈的中心点。缺商圈的用 EXTRA 兜底。"""
    acc: dict[str, list[float]] = {}
    with CSV_IN.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                lat, lng = float(row["lat"]), float(row["lng"])
            except (TypeError, ValueError):
                continue
            slot = acc.setdefault(row["area"], [0.0, 0.0, 0])
            slot[0] += lat
            slot[1] += lng
            slot[2] += 1

    centers = {name: (slot[1] / slot[2], slot[0] / slot[2]) for name, slot in acc.items()}

    # 现有数据里没有、但我们想补的商圈（手动给个中心）
    centers.setdefault("龙华", (114.0302, 22.6184))  # 壹方天地一带
    centers.setdefault("宝安中心", (113.8872, 22.5580))
    return centers


def cached_get(path: str, params: dict) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    sig = hashlib.sha1(
        json.dumps({"p": path, "q": params}, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    cache_file = CACHE / f"{sig}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    url = f"{BASE}/{path}"
    full = {**params, "key": settings.amap_key}
    last_error: Exception | None = None
    for attempt in range(1, 4):
        time.sleep(0.3 * attempt)  # 别把个人配额打得像攻击
        try:
            # 第 3 次改用直连（trust_env=False）。这台机器开着 127.0.0.1:7890 的
            # 系统代理，走它更快但偶尔报 SSL UNEXPECTED_EOF；直连慢一些但稳。
            with httpx.Client(timeout=20.0, trust_env=attempt < 3) as client:
                resp = client.get(url, params=full)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 - 网络抖动就重试，重试完还能跳过
            last_error = exc
            print(f"    重试 {attempt}/3：{type(exc).__name__}")
            continue

        if data.get("status") != "1":
            print(f"  !! {params.get('keywords')}: {data.get('info')} ({data.get('infocode')})")
            data = {"pois": []}
        cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    print(f"  !! 放弃这个查询（{params.get('keywords')}）：{last_error}")
    return {"pois": []}


def collect(centers: dict[str, tuple[float, float]]) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()

    for area, (lng, lat) in sorted(centers.items()):
        for keyword, radius in QUERIES:
            data = cached_get(
                "place/around",
                {
                    "location": f"{lng:.4f},{lat:.4f}",
                    "keywords": keyword,
                    "radius": radius,
                    "offset": 15,
                    "page": 1,
                    "extensions": "all",
                    "output": "json",
                },
            )
            pois = data.get("pois") or []
            kept = 0
            for p in pois:
                pid = str(p.get("id") or "")
                typecode = str(p.get("typecode") or "")
                cat = category_of(typecode)
                if not pid or not cat or pid in seen:
                    continue
                loc = str(p.get("location") or "")
                if "," not in loc:
                    continue
                lng_s, lat_s = loc.split(",", 1)
                biz = p.get("biz_ext") or {}

                def _scalar(v) -> str:
                    # 高德对缺失值会给空列表，不是 null
                    return "" if isinstance(v, list) else str(v or "")

                rows.append(
                    {
                        "amap_id": pid,
                        "name": str(p.get("name") or ""),
                        "area": area,
                        "district": str(p.get("adname") or ""),
                        "category": cat,
                        "lat": lat_s,
                        "lng": lng_s,
                        "avg_price": _scalar(biz.get("cost")),
                        "rating": _scalar(biz.get("rating")),
                        "typecode": typecode,
                        "amap_type": str(p.get("type") or ""),
                        "open_time": _scalar(biz.get("open_time")),
                        "address": _scalar(p.get("address")),
                        "distance": _scalar(p.get("distance")),
                        "keyword": keyword,
                    }
                )
                seen.add(pid)
                kept += 1
            print(f"  {area:<8} {keyword:<6} 返回 {len(pois):>2} 条，收下 {kept:>2}")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不请求")
    args = ap.parse_args()

    if not settings.amap_key:
        print("AMAP_KEY 是空的。把它填进 .env 再跑。")
        return 2

    centers = area_centers()
    total = len(centers) * len(QUERIES)
    print(f"商圈 {len(centers)} 个 × 关键词 {len(QUERIES)} 个 = {total} 次请求")
    if args.dry_run:
        for name, (lng, lat) in sorted(centers.items()):
            print(f"  {name:<10} center={lng:.4f},{lat:.4f}")
        return 0

    rows = collect(centers)
    if not rows:
        print("一条都没拉到，先查 key 和配额。")
        return 1

    fields = list(rows[0].keys())
    with CSV_OUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    by_area: dict[str, int] = {}
    by_cat: dict[str, int] = {}
    for r in rows:
        by_area[r["area"]] = by_area.get(r["area"], 0) + 1
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1

    print(f"\n共 {len(rows)} 条候选 → {CSV_OUT.relative_to(ROOT)}")
    print("按商圈:", "  ".join(f"{k} {v}" for k, v in sorted(by_area.items())))
    print("按品类:", "  ".join(f"{k} {v}" for k, v in sorted(by_cat.items())))
    print("\n下一步是人工补：indoor / quiet / min_people / max_people / kid_friendly /")
    print("need_booking / queue / tags / blurb —— 这 9 列高德一概不提供。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
