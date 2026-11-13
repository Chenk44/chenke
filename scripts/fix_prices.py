"""把「人均」按场所性质重算一遍。

背景：这批数据先用脚本按品类给了默认值（展览 60、玩乐 110、公园 0…），
凡是高德没给 cost 的都落到了默认值上，于是「南山书城 60 元」「大梅沙沙滩 127 元」
这种明显不对的数字混进了价格维度，直接影响预算计算。

规则只有两类：
1. 免费进入的场所（公园、海滩、书店、美术馆、博物馆、商场…）人均 = 0
2. 明确要买票 / 明确要花钱的，用 PAID 表里的人工价
其余（餐饮、咖啡、影院、密室、攀岩、球馆…）保持原值不动。

用法：
    python -m scripts.fix_prices            # 只看差异
    python -m scripts.fix_prices --write    # 写回 CSV
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "pois_shenzhen.csv"

# 进入不花钱的场所：关键词命中即免费
FREE_WORDS = (
    "公园",
    "海滩",
    "沙滩",
    "绿道",
    "栈道",
    "湿地",
    "广场",
    "古城",
    "步行街",
    "老街",
    "市集",
    "夜市",
    "书城",
    "书店",
    "书吧",
    "图书馆",
    "博物馆",
    "美术馆",
    "艺术馆",
    "展览馆",
    "纪念馆",
    "规划馆",
    "文化馆",
    "创意园",
    "创意文化园",
)

# 商场 / 购物中心：逛街本身不买票，人均按 0 算
MALL_WORDS = (
    "购物中心",
    "商场",
    "万象城",
    "万象天地",
    "COCO Park",
    "KKMALL",
    "KK one",
    "壹方城",
    "深业上城",
    "卓悦中心",
    "卓悦汇",
    "中心城",
    "领展",
    "连城新天地",
    "宝华楼",
    "聚宝商业中心",
    "欢乐颂",
    "益田假日",
    "8号仓",
    "奥特莱斯",
    "万科广场",
    "天虹",
    "虹湾",
    "中洲湾",
    "皇庭广场",
    "海岸城购物中心",
)

# 名字里带这些词的，就算命中上面的词也仍然是「要买票」的场所
NEVER_FREE = (
    "影城",
    "影院",
    "电影",
    "摩天轮",
    "观景台",
    "音乐厅",
    "大剧院",
    "攀岩",
    "羽毛球",
    "球馆",
    "滑冰",
    "保龄球",
    "密室",
    "剧本",
    "桌游",
    "KTV",
    "健身",
    "游泳",
    "网球",
    "射箭",
    "蹦床",
    "卡丁车",
    "游乐",
    "水世界",
)

# 明确要买票的：写死人工价（元/人）
PAID = {
    "仙湖植物园": 20,
    "深圳音乐厅": 120,
    "深圳大剧院": 100,
    "平安金融中心云际观景台": 200,
    "千户之屋故事美术馆": 173,
    "湾区之光摩天轮": 100,
    "深圳珠宝博物馆": 0,
    "深圳惠风古陶博物馆": 0,
    "诚品生活": 0,
    "较场尾": 0,
    "大鹏所城": 0,
    "德真文化体验馆": 0,
    "生物圈三号": 0,
    "钟书阁": 0,
    "海上世界文化艺术中心": 0,
}

# 这些品类的「人均」是真实消费金额，一律不动
UNTOUCHED = ("影院", "餐饮", "咖啡", "夜生活")


def guess_price(name: str, category: str, current: float) -> float | None:
    """返回新的价格；None 表示保持原值。"""
    for key, price in PAID.items():
        if key in name:
            return float(price)
    if any(word in name for word in NEVER_FREE):
        return None
    if category in UNTOUCHED:
        return None
    # 括号里通常是分店名或地址（「蓝天攀岩(福田体育公园店)」），只拿主干名判断
    primary = name.split("(")[0]
    if any(word in primary for word in FREE_WORDS):
        return 0.0
    if any(word in primary for word in MALL_WORDS):
        return 0.0
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    rows = list(csv.DictReader(CSV.open(encoding="utf-8")))
    fields = list(rows[0].keys())
    changed = []
    for row in rows:
        old = float(row["avg_price"] or 0)
        new = guess_price(row["name"], row["category"], old)
        if new is not None and abs(new - old) > 0.01:
            changed.append((row["category"], row["name"], old, new))
            row["avg_price"] = f"{new:.0f}"

    for cat, name, old, new in changed:
        print(f"{cat:4s} {old:6.0f} → {new:6.0f}  {name[:40]}")

    total = sum(float(r["avg_price"] or 0) for r in rows)
    print(
        f"\n改动 {len(changed)} / {len(rows)} 条；改后总价 {total:.0f} 元，"
        f"人均 {total / len(rows):.1f} 元"
    )

    if args.write:
        with CSV.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        print(f"已写回 {CSV}")
    else:
        print("（仅预览，加 --write 才会写回）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
