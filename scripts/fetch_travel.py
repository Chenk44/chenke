"""预计算「商圈 × 商圈」的通行时间，存成 `data/area_travel.csv`。

为什么要预计算而不是运行时调高德：
一次推荐里要算 24² 量级的两两时间，一次答辩跑五六遍就是几千次请求，
免费配额（个人开发者 5000 次/天）会被当场打光，网络一抖演示就断。

这里只算 20 个商圈的两两组合（190 对 × 2 种交通方式 = 380 次请求），
结果落成一张表跟着仓库走：合并进仓库后，评委断网也能跑，
而且 `algo/travel.py` 只在表里查不到时才退回球面距离估算。

跑法：
    python -m scripts.fetch_travel            # 用缓存，缺的才请求
    python -m scripts.fetch_travel --refresh  # 忽略缓存全量重拉
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import sys
import time
from itertools import combinations
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from algo.loader import area_centroid, areas, load_pois  # noqa: E402

CACHE = ROOT / ".tmp" / "amap_travel_cache"
OUT = ROOT / "data" / "area_travel.csv"
BASE = "https://restapi.amap.com/v3/direction"

with contextlib.suppress(AttributeError, OSError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_key() -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("AMAP_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _cache_path(name: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE / f"{hashlib.sha1(name.encode()).hexdigest()}.json"


def cached_get(client: httpx.Client, url: str, params: dict, refresh: bool = False) -> dict | None:
    key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "key")
    path = _cache_path(key)
    if path.exists() and not refresh:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    for attempt in range(3):
        try:
            # 本机开着系统代理，偶发 SSL UNEXPECTED_EOF，最后一次强制直连
            client_kwargs = {"trust_env": attempt < 2}
            with httpx.Client(timeout=25, **client_kwargs) as c:
                resp = c.get(url, params=params)
            data = resp.json()
            if data.get("status") == "1":
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                return data
            if data.get("infocode") in {"10001", "10003"}:  # key 无效 / 超配额，别重试了
                print(f"  ! {data.get('info')}", file=sys.stderr)
                return None
        except (httpx.HTTPError, ValueError):
            time.sleep(1.0 + attempt)
    return None


def drive_minutes(data: dict | None) -> float | None:
    paths = ((data or {}).get("route") or {}).get("paths") or []
    if not paths:
        return None
    return round(int(paths[0]["duration"]) / 60.0, 1)


def transit_minutes(data: dict | None) -> float | None:
    transits = ((data or {}).get("route") or {}).get("transits") or []
    if not transits:
        return None
    # 多条换乘方案里取最快的那条，用户出门当然挑最快的
    return round(min(int(t["duration"]) for t in transits) / 60.0, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    key = load_key()
    if not key:
        print("❌ .env 里没有 AMAP_KEY", file=sys.stderr)
        return 1

    pois = load_pois()
    names = areas(pois)
    coords = {a: area_centroid(pois, a) for a in names}
    pairs = list(combinations(names, 2))
    print(f"商圈 {len(names)} 个，两两 {len(pairs)} 对，各查驾车 + 公交")

    rows: list[str] = []
    ok = miss = 0
    with httpx.Client(timeout=25, trust_env=False) as client:
        for i, (a, b) in enumerate(pairs, 1):
            (la, oa), (lb, ob) = coords[a], coords[b]
            origin, dest = f"{oa},{la}", f"{ob},{lb}"
            d = drive_minutes(
                cached_get(
                    client,
                    f"{BASE}/driving",
                    {"origin": origin, "destination": dest, "extensions": "base", "key": key},
                    args.refresh,
                )
            )
            t = transit_minutes(
                cached_get(
                    client,
                    f"{BASE}/transit/integrated",
                    {"origin": origin, "destination": dest, "city": "深圳", "key": key},
                    args.refresh,
                )
            )
            if d is None and t is None:
                miss += 1
                continue
            ok += 1
            rows.append(f"{a},{b},{d if d is not None else ''},{t if t is not None else ''}")
            rows.append(f"{b},{a},{d if d is not None else ''},{t if t is not None else ''}")
            if i % 20 == 0:
                print(f"  {i}/{len(pairs)} ...", flush=True)
            time.sleep(0.2)

    header = "from_area,to_area,drive_minutes,transit_minutes"
    OUT.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    print(f"✅ 完成：成功 {ok} 对，失败 {miss} 对 → {OUT.relative_to(ROOT)}（{len(rows)} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
