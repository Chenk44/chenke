"""把营业时间回填进 `data/pois_shenzhen.csv`（新增 open_hour / close_hour 两列）。

数据来源优先级：
    1. 高德 `place/text` 返回的 `open_time`（`data/amap_shortlist.csv` 里存着，按名字匹配）
    2. 名字/品类先验（`scripts/open_hours.py: default_hours`）

跑法：
    python -m scripts.backfill_hours            # 只报告，不写文件
    python -m scripts.backfill_hours --write    # 真的写回 CSV
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from scripts.open_hours import default_hours, parse_open_time

ROOT = Path(__file__).resolve().parent.parent
POIS = ROOT / "data" / "pois_shenzhen.csv"
SHORTLIST = ROOT / "data" / "amap_shortlist.csv"

_PARENS = re.compile(r"[（(].*?[)）]")


def _key(name: str) -> str:
    """去掉括号后缀再比对：「西贝莜面村(海岸城)」和「西贝莜面村」算同一家。"""
    return _PARENS.sub("", name).strip().lower()


def load_open_times() -> dict[str, str]:
    """高德的时间表：名字 → open_time 原文。先出现的优先（短名单已按评分排过）。"""
    if not SHORTLIST.exists():
        return {}
    table: dict[str, str] = {}
    with SHORTLIST.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            name, raw = (row.get("name") or "").strip(), (row.get("open_time") or "").strip()
            if not name or not raw:
                continue
            table.setdefault(_key(name), raw)
            table.setdefault(name.strip().lower(), raw)
    return table


def _fmt(hour: float) -> str:
    if hour == int(hour):
        return str(int(hour))
    return f"{hour:.1f}".rstrip("0").rstrip(".")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="写回 CSV（默认只统计）")
    args = parser.parse_args()

    table = load_open_times()
    with POIS.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)

    for col in ("open_hour", "close_hour"):
        if col not in fields:
            fields.append(col)

    from_amap = from_default = 0
    for row in rows:
        name = (row.get("name") or "").strip()
        parsed = parse_open_time(table.get(_key(name)) or table.get(name.lower()))
        if parsed is None:
            parsed = default_hours(name, (row.get("category") or "").strip())
            from_default += 1
        else:
            from_amap += 1
        row["open_hour"] = _fmt(parsed[0])
        row["close_hour"] = _fmt(parsed[1])

    print(f"共 {len(rows)} 条：高德给了 {from_amap} 条，按名字/品类兜底 {from_default} 条")

    late = [r for r in rows if float(r["close_hour"]) >= 24]
    early = [r for r in rows if float(r["close_hour"]) <= 20]
    print(f"打烊 ≥ 24:00 的 {len(late)} 条；≤ 20:00 的 {len(early)} 条")
    for r in early[:5]:
        print(f"  早关门：{r['name']} {r['open_hour']}-{r['close_hour']}")

    if not args.write:
        print("（未写文件，加 --write 才会回填 CSV）")
        return

    with POIS.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"已写回 {POIS.relative_to(ROOT)}，记得跑 python -m scripts.seed 同步数据库")


if __name__ == "__main__":
    main()
