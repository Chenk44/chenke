"""数据体检：把「脚本猜出来、可能猜错」的标注挑出来，让人只复核有问题的那几行。

用法：
    python -m scripts.audit_pois            # 打印报告
    python -m scripts.audit_pois --csv      # 另外把可疑行写成 .tmp/audit.csv

设计原则：只报「可疑」，不擅自改数据。改 CSV 一行 + 重跑 seed 是唯一入口。
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

from algo.loader import load_pois
from scripts.open_hours import OUTDOOR_WORDS

ROOT = Path(__file__).resolve().parent.parent
AUDIT_CSV = ROOT / ".tmp" / "audit.csv"

INDOOR_NAME_WORDS = (
    "商场", "购物中心", "影城", "影院", "博物馆", "美术馆", "书店", "图书馆",
    "KTV", "密室", "剧本", "桌游", "咖啡", "餐厅", "酒楼", "料理",
)  # fmt: skip

MEAL_CATEGORIES = {"餐饮", "咖啡", "夜生活"}


def audit() -> list[tuple[str, str, str, str]]:
    """返回 (问题类型, 地点 id, 地点名, 说明) 的列表。"""
    pois = load_pois()
    issues: list[tuple[str, str, str, str]] = []

    for poi in pois:
        if poi.category == "公园" and poi.indoor:
            issues.append(("室内外", poi.id, poi.name, "品类是公园却标成室内"))
        elif poi.indoor and any(w in poi.name for w in OUTDOOR_WORDS):
            issues.append(("室内外", poi.id, poi.name, "名字像户外却标成室内"))
        elif not poi.indoor and any(w in poi.name for w in INDOOR_NAME_WORDS):
            issues.append(("室内外", poi.id, poi.name, "名字像室内却标成室外"))

        if poi.category in MEAL_CATEGORIES and poi.avg_price <= 0:
            issues.append(("人均", poi.id, poi.name, f"{poi.category}的人均是 0，像是没采到"))
        elif poi.avg_price > 800:
            issues.append(("人均", poi.id, poi.name, f"人均 {poi.avg_price} 元，核对一下"))

        if poi.rating < 3.5:
            issues.append(("评分", poi.id, poi.name, f"评分只有 {poi.rating}"))

        span = poi.close_hour - poi.open_hour
        if span < 2:
            issues.append(("营业时间", poi.id, poi.name, f"只开 {span:.1f} 小时"))
        if poi.open_hour >= 22:
            issues.append(
                ("营业时间", poi.id, poi.name, f"{poi.open_hour:.0f} 点才开门，像不像写反了")
            )

        if not poi.tags:
            issues.append(("标签", poi.id, poi.name, "没有标签"))
        if len(poi.blurb) < 6:
            issues.append(("理由", poi.id, poi.name, "一句话理由太短或为空"))

    # 商圈层面的问题单独报
    outdoor_by_area: dict[str, int] = defaultdict(int)
    total_by_area: Counter[str] = Counter()
    for poi in pois:
        total_by_area[poi.area] += 1
        if not poi.indoor:
            outdoor_by_area[poi.area] += 1
    for area, total in total_by_area.items():
        if outdoor_by_area[area] < 3:
            issues.append(
                ("覆盖", "-", area, f"只有 {outdoor_by_area[area]} 个室外点（共 {total} 个）")
            )

    # 同名且很近 = 合并没有去重成功
    for i, a in enumerate(pois):
        for b in pois[i + 1 :]:
            if a.name == b.name and abs(a.lat - b.lat) < 0.01 and abs(a.lng - b.lng) < 0.01:
                issues.append(("重复", a.id, a.name, f"和 {b.id} 是同一个地方"))

    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="地点库体检")
    parser.add_argument("--csv", action="store_true", help="把可疑行写进 .tmp/audit.csv")
    args = parser.parse_args()

    pois = load_pois()
    issues = audit()

    print(f"地点 {len(pois)} 条，可疑 {len(issues)} 处")
    by_kind: Counter[str] = Counter(kind for kind, *_ in issues)
    print("分类：" + "，".join(f"{k} {v}" for k, v in by_kind.most_common()))

    for kind in by_kind:
        rows = [row for row in issues if row[0] == kind]
        print(f"\n── {kind}（{len(rows)}）")
        for _, poi_id, name, why in rows[:12]:
            print(f"   {poi_id:>8}  {name}  —— {why}")
        if len(rows) > 12:
            print(f"   …… 还有 {len(rows) - 12} 条")

    if args.csv:
        AUDIT_CSV.parent.mkdir(parents=True, exist_ok=True)
        AUDIT_CSV.write_text(
            "问题类型,id,名称,说明\n" + "\n".join(",".join(row) for row in issues),
            encoding="utf-8",
        )
        print(f"\n已写出 {AUDIT_CSV}")


if __name__ == "__main__":
    main()
