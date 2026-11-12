"""把高德短名单压成一份「带草稿标注」的地点表。

为什么要这一步：653 条候选里真正能进产品的只有一百多条，而人工标注 9 个字段
（室内外/安静度/人数/带娃/预约/排队/标签/理由）如果从零开始打，一下午就没了。

这里的策略是：**能自动算的自动算，算不出来的按品类给一个合理先验，
人工只需要改「不对的那几条」**。所以每一条都附一个 `draft_note` 说明
这个值是怎么来的——改的时候知道从哪里下手。

注意输出到 `data/pois_draft.csv`，**不碰** `data/pois_shenzhen.csv`。
人工复核完、确认无误后再合并。

用法::

    python -m scripts.draft_labels               # 每商圈 8 条
    python -m scripts.draft_labels --per-area 10
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IN_CSV = ROOT / "data" / "amap_shortlist.csv"
OUT_CSV = ROOT / "data" / "pois_draft.csv"

# 高德的品类 → 算法里的 7 个品类（CATEGORIES 是封闭集合，不能随手加）
CATEGORY_MAP = {
    "书店": "展览",  # 「美术馆 / 展馆 / 书店」本来就是一档
    "运动": "玩乐",
    "市集": "夜生活",  # 夜市 / 市集 = 逛吃
}

# 各品类的默认值。数字是拍出来的先验，人工复核时主要改这些。
DEFAULTS: dict[str, dict] = {
    "公园": {"price": 0, "quiet": 0.75, "people": (2, 10), "kid": True, "queue": 0.15},
    "展览": {"price": 60, "quiet": 0.6, "people": (2, 6), "kid": True, "queue": 0.35},
    "咖啡": {"price": 35, "quiet": 0.45, "people": (1, 4), "kid": True, "queue": 0.55},
    "餐饮": {"price": 80, "quiet": 0.4, "people": (2, 8), "kid": True, "queue": 0.45},
    "影院": {"price": 55, "quiet": 0.3, "people": (2, 6), "kid": True, "queue": 0.25},
    "夜生活": {"price": 90, "quiet": 0.2, "people": (2, 8), "kid": False, "queue": 0.4},
    "玩乐": {"price": 110, "quiet": 0.3, "people": (3, 8), "kid": False, "queue": 0.5},
}

# 和 scripts/shortlist.py 的 OUTDOOR_WORDS 保持一致。
# 「山」「湾」「广场」不能放进来：「岚山庭」是日料店、「建设广场店」是门店地址，
# 会把室内店误判成户外，进而把「不想去室内」的推荐又带偏。
OUTDOOR_NAME_WORDS = (
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

# 高德会返回还没开、或者已经关掉的地方。这些直接扔掉，
# 不然方案里会出现「去一个还在地基里的乐园」。
DEAD_NAME_WORDS = (
    "建设中",
    "不对外开放",
    "暂停营业",
    "已关闭",
    "关闭",
    "装修改造",
    "整修",
    "停业",
    "待开业",
    "未开业",
    "施工",
    "搬迁",
)

# 高德的 typecode 会把夜市、步行街归到「公园」里，按名字纠正一下
NAME_CATEGORY_FIX = (
    (("夜市", "市集", "步行街", "美食街"), "夜生活"),
    (("沙滩", "海滩"), "公园"),
)

# 名字没命中关键词时，按品类兜个底，避免标签栏只剩品类名
TAG_FALLBACK: dict[str, tuple[str, ...]] = {
    "公园": ("户外", "散步"),
    "展览": ("看展", "拍照"),
    "餐饮": ("吃饭",),
    "咖啡": ("咖啡", "坐着"),
    "影院": ("电影",),
    "夜生活": ("夜市", "逛吃"),
    "玩乐": ("玩乐",),
}

# 一句话理由的草稿模板：{area} {price}
BLURB_PAID: dict[str, str] = {
    "餐饮": "{area}吃饭，人均 {price} 元",
    "咖啡": "{area}坐一下午，人均 {price} 元",
    "展览": "{area}看展，人均 {price} 元",
    "影院": "{area}看电影，人均 {price} 元",
    "玩乐": "{area}玩一场，人均 {price} 元",
    "夜生活": "{area}晚上逛，人均 {price} 元",
    "公园": "{area}走走，人均 {price} 元",
}
BLURB_FREE: dict[str, str] = {
    "公园": "{area}散个步，不花钱",
    "夜生活": "{area}逛街，不花钱",
    "展览": "{area}看展，不花钱",
}

# 名字里的关键词 → (标签, 强制 indoor 值或 None, 是否要预约)
TAG_RULES: tuple[tuple[tuple[str, ...], str, bool | None, bool], ...] = (
    (("密室",), "密室|组队", True, True),
    (("剧本",), "剧本杀|组队", True, True),
    (("桌游",), "桌游|组队", True, False),
    (("KTV", "ktv", "唱"), "KTV|唱歌", True, True),
    (("影城", "电影", "影院"), "电影|空调", True, False),
    (("美术馆", "博物馆", "展"), "看展|拍照", True, False),
    (("书店", "书城"), "书店|安静", True, False),
    (("咖啡", "coffee", "Coffee"), "咖啡|坐着", True, False),
    (("羽毛球", "健身", "攀岩", "滑冰", "冰场"), "运动|出汗", True, True),
    (("沙滩", "海滩"), "海边|拍照", False, False),
    (("公园", "绿道", "栈道", "湿地", "海滩"), "户外|散步", False, False),
    (("夜市", "市集"), "夜市|逛吃", False, False),
    (("商场", "购物中心"), "商场|空调|逛街", True, False),
)


def pick_rows(rows: list[dict], per_area: int) -> list[dict]:
    """每个商圈挑 per_area 条：先保证品类与室外覆盖，再用评分填满。"""
    by_area: dict[str, list[dict]] = {}
    for row in rows:
        by_area.setdefault(row["area"], []).append(row)

    def rating(row: dict) -> float:
        try:
            return float(row["rating"])
        except (TypeError, ValueError):
            return 0.0

    chosen: list[dict] = []
    for _area, group in sorted(by_area.items()):
        group.sort(key=lambda r: -rating(r))
        picked: list[dict] = []
        used_cat: dict[str, int] = {}
        outdoor = 0

        def outdoor_of(row: dict) -> bool:
            return row["indoor_guess"] == "false"

        # 第一轮：每个品类先各来一条（保证方案里能凑出「咖啡+展览+吃饭」）。
        # 但**故意只填到 per_area-3**，把后面三个位置留给室外平衡——
        # 否则第一轮就把名额占满，室外永远是 1-2 条。
        reserve = 3
        for row in group:
            cat = CATEGORY_MAP.get(row["category"], row["category"])
            if used_cat.get(cat, 0) == 0 and len(picked) < max(1, per_area - reserve):
                picked.append(row)
                used_cat[cat] = 1
                outdoor += 1 if outdoor_of(row) else 0

        # 第二轮：室内外平衡。室外不足 3 条时优先补室外
        for row in group:
            if len(picked) >= per_area:
                break
            if row in picked:
                continue
            cat = CATEGORY_MAP.get(row["category"], row["category"])
            if outdoor < 3 and not outdoor_of(row):
                continue
            if used_cat.get(cat, 0) >= 3:
                continue
            picked.append(row)
            used_cat[cat] = used_cat.get(cat, 0) + 1
            outdoor += 1 if outdoor_of(row) else 0

        # 第三轮：还差就按评分硬填
        for row in group:
            if len(picked) >= per_area:
                break
            if row in picked:
                continue
            picked.append(row)

        chosen.extend(picked)
    return chosen


def draft_labels(row: dict) -> dict:
    """给一条候选补上 9 个人工字段的草稿值。"""
    name = row["name"]
    cat = CATEGORY_MAP.get(row["category"], row["category"])
    base = DEFAULTS[cat]

    tags: list[str] = []
    indoor_forced: bool | None = None
    booking = False
    for words, tag_str, indoor_value, need_booking in TAG_RULES:
        if any(word in name for word in words):
            for tag in tag_str.split("|"):
                if tag not in tags:
                    tags.append(tag)
            if indoor_forced is None and indoor_value is not None:
                indoor_forced = indoor_value
            booking = booking or need_booking

    outdoor_by_name = any(word in name for word in OUTDOOR_NAME_WORDS)
    guess = row.get("indoor_guess") or ""
    if outdoor_by_name:
        indoor = False
        if "户外" not in tags and "海边" not in tags:
            tags.insert(0, "户外")
    elif guess == "false":
        # 短名单里已经判成室外的（步行街、美食街这种名字里没山没水的），
        # 以它为准——否则「东门商业步行街」会被品类先验拉回室内
        indoor = False
    elif indoor_forced is not None:
        indoor = indoor_forced
    elif guess == "true":
        indoor = True
    else:
        # 品类先验：公园室外，其他默认室内
        indoor = cat != "公园"

    try:
        price = float(row["avg_price"]) if row["avg_price"] else float(base["price"])
    except ValueError:
        price = float(base["price"])

    try:
        rating = float(row["rating"])
    except (TypeError, ValueError):
        rating = 4.2

    # 安静度按评分微调（评分高的地方通常管理更好、更不吵），保持确定性
    quiet = round(min(0.95, max(0.05, base["quiet"] + (rating - 4.2) * 0.04)), 2)

    min_people, max_people = base["people"]
    if "组队" in "|".join(tags):
        min_people = max(min_people, 4)

    if not tags:
        # 名字里没命中任何关键词时，至少按品类给个像样的标签，
        # 否则表格里会出现孤零零的「公园」两个字（如「深圳仙湖植物园」）
        tags = TAG_FALLBACK.get(cat, (cat,))

    area = row["area"]
    if price <= 0:
        blurb = BLURB_FREE.get(cat, f"{area}走走，不花钱").format(area=area)
    else:
        blurb = BLURB_PAID.get(cat, f"{area}逛一圈，人均 {{price}} 元").format(
            area=area, price=f"{price:.0f}"
        )

    return {
        "id": f"am-{row['amap_id'].lower()}",
        "name": name,
        "area": row["area"],
        "district": row["district"],
        "category": cat,
        "lat": row["lat"],
        "lng": row["lng"],
        "avg_price": f"{price:.0f}",
        "rating": f"{rating:.1f}",
        "indoor": "true" if indoor else "false",
        "quiet": f"{quiet:.2f}",
        "min_people": str(min_people),
        "max_people": str(max_people),
        "kid_friendly": "true" if base["kid"] else "false",
        "need_booking": "true" if booking else "false",
        "queue": f"{base['queue']:.2f}",
        "tags": "|".join(tags[:3]),
        "blurb": blurb,
    }


FIELDS = [
    "id",
    "name",
    "area",
    "district",
    "category",
    "lat",
    "lng",
    "avg_price",
    "rating",
    "indoor",
    "quiet",
    "min_people",
    "max_people",
    "kid_friendly",
    "need_booking",
    "queue",
    "tags",
    "blurb",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-area", type=int, default=8)
    args = ap.parse_args()

    if not IN_CSV.exists():
        print(f"缺少 {IN_CSV.relative_to(ROOT)}，先跑 python -m scripts.shortlist")
        return 2

    with IN_CSV.open(encoding="utf-8") as f:
        raw_rows = list(csv.DictReader(f))

    # 先剔掉没开、关掉、在建的地方，再纠正被 typecode 归错的品类
    rows = [row for row in raw_rows if not any(w in row["name"] for w in DEAD_NAME_WORDS)]
    dropped = len(raw_rows) - len(rows)
    for row in rows:
        for words, fixed in NAME_CATEGORY_FIX:
            if any(w in row["name"] for w in words):
                row["category"] = fixed
                break

    picked = pick_rows(rows, args.per_area)
    labeled = [draft_labels(row) for row in picked]

    # id 不能重复，否则 loader 会拒
    seen: set[str] = set()
    deduped: list[dict] = []
    for row in labeled:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        deduped.append(row)

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(deduped)

    print(
        f"短名单 {len(rows)} 条（剔掉在建/关闭 {dropped} 条）→ 草稿 {len(deduped)} 条 → {OUT_CSV.relative_to(ROOT)}\n"
    )

    by_area: dict[str, list[dict]] = {}
    for row in deduped:
        by_area.setdefault(row["area"], []).append(row)
    print("商圈覆盖（总/室外/室内）：")
    for area, group in sorted(by_area.items()):
        outdoor = sum(1 for r in group if r["indoor"] == "false")
        print(f"  {area:<8} {len(group):>2}  室外 {outdoor:>2}  室内 {len(group) - outdoor:>2}")

    by_cat: dict[str, int] = {}
    for row in deduped:
        by_cat[row["category"]] = by_cat.get(row["category"], 0) + 1
    print("\n品类分布:", "  ".join(f"{k} {v}" for k, v in sorted(by_cat.items())))

    # 用真正的 loader 验一遍，避免数据集里混进非法品类/空字段
    import sys

    sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
    from algo.loader import load_pois  # noqa: E402

    pois = load_pois(OUT_CSV)
    print(f"\n正版 loader 校验通过：{len(pois)} 条，{len({p.area for p in pois})} 个商圈")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
