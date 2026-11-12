"""把 1685 条高德候选压成一份能人工过一遍的短名单。

1685 条是没法手工标注的——光看名字就要一小时，而且大部分是「某某便利店」
「某某小区南门」这种跟「去哪玩」无关的东西。这一步做三件事：

1. **去重品牌**：同一个品牌在三个商圈各开一家，只保留每个商圈里评分最高的那个，
   同名连锁（去掉括号里的分店后缀后同名）只留一条；
2. **每个商圈每个品类留 top 5**，按「有评分的优先 → 评分高 → 距离近」排序；
3. 给一个 **室内外粗猜**（`indoor_guess`），只用于筛选和统计，
   最终 indoor 列仍然要人工改——高德的 indoor_map 字段实测不可信
   （商场=1、公园=0，但 KTV 也=0）。

用法::

    python -m scripts.shortlist            # 生成 data/amap_shortlist.csv
    python -m scripts.shortlist --top 8    # 每商圈每品类留 8 条
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IN_CSV = ROOT / "data" / "amap_candidates.csv"
OUT_CSV = ROOT / "data" / "amap_shortlist.csv"

# 品类 → 室内外先验。只用来排序和统计，标注时仍以人判断为准。
INDOOR_BY_CATEGORY = {
    "影院": True,
    "书店": True,
    "展览": True,
    "咖啡": True,
    "运动": True,
    "玩乐": None,  # 商场室内、密室室内、市集室外，混着
    "餐饮": True,
    "公园": False,
    "市集": False,
}

# 名字里带这些词的基本可以确定是室外。
# 刻意不放「山」「湾」「广场」——「岚山庭」是日料店、「建设广场店」是门店地址，
# 这两个字在店名里出现得太频繁，会把室内店误判成户外。
OUTDOOR_WORDS = (
    "公园",
    "海滩",
    "沙滩",
    "绿道",
    "栈道",
    "湿地",
    "海滨",
    "海边",
    "登山",
    "爬山",
    "摩天轮",
    "露天",
    "户外",
)


def normalize_name(name: str) -> str:
    """去掉分店后缀，用来判重：「喜茶(海岸城店)」和「喜茶(万象城店)」算同一品牌。"""
    s = re.sub(r"[（(].*?[)）]", "", name)
    return re.sub(r"\s+", "", s).casefold()


def guess_indoor(row: dict) -> str:
    name = row["name"]
    if any(w in name for w in OUTDOOR_WORDS):
        return "false"
    prior = INDOOR_BY_CATEGORY.get(row["category"])
    if prior is None:
        # 「玩乐」品类里挑几个明确室内的关键词
        if any(w in name for w in ("密室", "剧本", "桌游", "KTV", "ktv", "影城", "电玩")):
            return "true"
        return ""
    return "true" if prior else "false"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=5, help="每个商圈每个品类保留几条")
    args = ap.parse_args()

    if not IN_CSV.exists():
        print(f"缺少 {IN_CSV.relative_to(ROOT)}，先跑 python -m scripts.fetch_amap")
        return 2

    with IN_CSV.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    def rating(row: dict) -> float:
        try:
            return float(row["rating"])
        except (TypeError, ValueError):
            return 0.0

    def distance(row: dict) -> float:
        try:
            return float(row["distance"])
        except (TypeError, ValueError):
            return 9999.0

    # 1) 同商圈内同品牌只留一条
    best: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["area"], normalize_name(row["name"]))
        current = best.get(key)
        if current is None or (rating(row), -distance(row)) > (
            rating(current),
            -distance(current),
        ):
            best[key] = row

    # 2) 每个（商圈, 品类）按分数取前 N
    buckets: dict[tuple[str, str], list[dict]] = {}
    for row in best.values():
        buckets.setdefault((row["area"], row["category"]), []).append(row)

    picked: list[dict] = []
    for (_area, _cat), group in sorted(buckets.items()):
        group.sort(key=lambda r: (-rating(r), distance(r)))
        picked.extend(group[: args.top])

    # 3) 按商圈、品类、评分排序，方便人工从头往下看
    picked.sort(key=lambda r: (r["area"], r["category"], -rating(r), distance(r)))

    by_area: dict[str, dict[str, int]] = {}
    for row in picked:
        row["indoor_guess"] = guess_indoor(row)
        slot = by_area.setdefault(row["area"], {})
        slot[row["indoor_guess"] or "?"] = slot.get(row["indoor_guess"] or "?", 0) + 1

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(picked[0].keys()))
        writer.writeheader()
        writer.writerows(picked)

    print(f"{len(rows)} 条候选 → 去重后 {len(best)} 条 → 短名单 {len(picked)} 条")
    print(f"写入 {OUT_CSV.relative_to(ROOT)}\n")
    print("商圈覆盖（室内 / 室外 / 待定）：")
    thin: list[str] = []
    for area, stat in sorted(by_area.items()):
        total = sum(stat.values())
        outdoor = stat.get("false", 0)
        flag = "" if outdoor >= 3 else "  ← 室外不足 3 个"
        if outdoor < 3:
            thin.append(area)
        print(
            f"  {area:<8} 共 {total:>2}  室内 {stat.get('true', 0):>2}  "
            f"室外 {outdoor:>2}  待定 {stat.get('?', 0):>2}{flag}"
        )
    if thin:
        print(f"\n需要优先补室外点位的商圈：{'、'.join(thin)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
