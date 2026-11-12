"""把草稿标注合并进正式数据集：人工那 49 条优先，草稿只补缺。"""

import csv
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

OLD = ROOT / "data" / "pois_shenzhen.csv"
DRAFT = ROOT / "data" / "pois_draft.csv"

# 同一条街上的两家分店（喜茶海岸城店 / 喜茶万象城店）是两回事，
# 但「深圳湾万象城」被两个商圈各抓一次是同一回事——
# 所以同名 + 800 米内才算重复。
SAME_PLACE_METERS = 800.0


def norm(name: str) -> str:
    for sep in ("(", "（"):
        name = name.split(sep)[0]
    return name.strip()


def meters(a: dict, b: dict) -> float:
    lat1, lng1 = math.radians(float(a["lat"])), math.radians(float(a["lng"]))
    lat2, lng2 = math.radians(float(b["lat"])), math.radians(float(b["lng"]))
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def is_dup(row: dict, pool: list[dict]) -> bool:
    name = norm(row["name"])
    for other in pool:
        if norm(other["name"]) == name and meters(row, other) < SAME_PLACE_METERS:
            return True
    return False


old = list(csv.DictReader(OLD.open(encoding="utf-8")))
draft = list(csv.DictReader(DRAFT.open(encoding="utf-8")))
fields = list(old[0].keys())

merged = list(old)
added: list[dict] = []
added_ids: set[str] = set()
for row in draft:
    if row["id"] in added_ids or is_dup(row, merged):
        continue
    added_ids.add(row["id"])
    merged.append(row)
    added.append(row)

with OLD.open("w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(merged)

print(f"原 {len(old)} + 草稿新增 {len(added)} = {len(merged)} 条")
by_area: dict[str, int] = {}
outdoor: dict[str, int] = {}
for row in merged:
    by_area[row["area"]] = by_area.get(row["area"], 0) + 1
    if row["indoor"] == "false":
        outdoor[row["area"]] = outdoor.get(row["area"], 0) + 1
for area in sorted(by_area):
    print(f"  {area:<8} 共 {by_area[area]:>2}  室外 {outdoor.get(area, 0):>2}")
print(
    f"\n合计 室外 {sum(outdoor.values())} / 室内 {len(merged) - sum(outdoor.values())}"
)
