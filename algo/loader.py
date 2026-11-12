"""把 `data/pois_shenzhen.csv` 读成 POI 对象。

为什么用 CSV 而不是直接写死在代码里：
1. 这张表是项目最核心的资产，要能被人肉编辑、被 Git 看到每一行改动；
2. 换城市 / 加地点不需要改代码；
3. 导入时就做校验，脏数据在启动阶段就报错，而不是上线后算出离谱结果。
"""

from __future__ import annotations

import csv
from pathlib import Path

from .types import CATEGORIES, POI

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "data" / "pois_shenzhen.csv"

REQUIRED_COLUMNS = (
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
)


class POIDataError(ValueError):
    """地点表格式错误。启动即失败，避免脏数据流入算法。"""


def _bool(raw: str, where: str) -> bool:
    v = (raw or "").strip().lower()
    if v in {"true", "1", "yes", "y", "是"}:
        return True
    if v in {"false", "0", "no", "n", "否", ""}:
        return False
    raise POIDataError(f"{where}: 无法解析布尔值 {raw!r}")


def _float(raw: str, where: str) -> float:
    try:
        return float((raw or "").strip())
    except (TypeError, ValueError) as exc:
        raise POIDataError(f"{where}: 无法解析数字 {raw!r}") from exc


def _int(raw: str, where: str) -> int:
    try:
        return int(float((raw or "").strip()))
    except (TypeError, ValueError) as exc:
        raise POIDataError(f"{where}: 无法解析整数 {raw!r}") from exc


def load_pois(path: str | Path | None = None) -> list[POI]:
    """读取并校验地点表。任何一行不合规都会抛 POIDataError。"""
    csv_path = Path(path) if path else DEFAULT_CSV
    if not csv_path.exists():
        raise POIDataError(f"地点表不存在：{csv_path}")

    pois: list[POI] = []
    seen: set[str] = set()

    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise POIDataError(f"缺少列：{sorted(missing)}")
        has_hours = {"open_hour", "close_hour"} <= set(reader.fieldnames or ())

        for lineno, row in enumerate(reader, start=2):
            where = f"{csv_path.name}:{lineno}"
            pid = (row["id"] or "").strip()
            if not pid:
                continue  # 允许空行和注释行
            if pid in seen:
                raise POIDataError(f"{where}: 重复的 id {pid!r}")
            seen.add(pid)

            category = (row["category"] or "").strip()
            if category not in CATEGORIES:
                raise POIDataError(f"{where}: 未知品类 {category!r}，应为 {CATEGORIES}")

            lat, lng = _float(row["lat"], where), _float(row["lng"], where)
            if not (20.0 < lat < 25.0 and 112.0 < lng < 116.0):
                raise POIDataError(f"{where}: 经纬度不在深圳范围 lat={lat} lng={lng}")

            rating = _float(row["rating"], where)
            if not 0.0 <= rating <= 5.0:
                raise POIDataError(f"{where}: rating 越界 {rating}")

            quiet = _float(row["quiet"], where)
            queue = _float(row["queue"], where)
            for label, value in (("quiet", quiet), ("queue", queue)):
                if not 0.0 <= value <= 1.0:
                    raise POIDataError(f"{where}: {label} 必须在 0~1，实际 {value}")

            min_people = _int(row["min_people"], where)
            max_people = _int(row["max_people"], where)
            if min_people > max_people:
                raise POIDataError(f"{where}: min_people > max_people")

            tags = tuple(t.strip() for t in (row["tags"] or "").split("|") if t.strip())

            open_hour, close_hour = 0.0, 24.0
            if has_hours:
                raw_open = (row.get("open_hour") or "").strip()
                raw_close = (row.get("close_hour") or "").strip()
                open_hour = _float(raw_open, where) if raw_open else 0.0
                close_hour = _float(raw_close, where) if raw_close else 24.0
                # 允许 close_hour 到 26 表示「凌晨两点打烊」，但不允许更离谱的值
                if not 0.0 <= open_hour < 24.0:
                    raise POIDataError(f"{where}: open_hour 越界 {open_hour}")
                if not open_hour < close_hour <= 26.0:
                    raise POIDataError(
                        f"{where}: close_hour 必须大于 open_hour 且不超过 26，实际 {close_hour}"
                    )

            pois.append(
                POI(
                    id=pid,
                    name=row["name"].strip(),
                    area=row["area"].strip(),
                    district=row["district"].strip(),
                    category=category,
                    lat=lat,
                    lng=lng,
                    avg_price=_float(row["avg_price"], where),
                    rating=rating,
                    indoor=_bool(row["indoor"], where),
                    quiet=quiet,
                    min_people=min_people,
                    max_people=max_people,
                    kid_friendly=_bool(row["kid_friendly"], where),
                    need_booking=_bool(row["need_booking"], where),
                    queue=queue,
                    tags=tags,
                    blurb=(row["blurb"] or "").strip(),
                    open_hour=open_hour,
                    close_hour=close_hour,
                )
            )

    if not pois:
        raise POIDataError(f"{csv_path} 里没有有效数据")
    return pois


def area_centroid(pois: list[POI], area: str) -> tuple[float, float]:
    """某个商圈的中心点，用作默认出发点。"""
    members = [p for p in pois if p.area == area]
    if not members:
        raise KeyError(f"没有这个商圈：{area}")
    return (
        sum(p.lat for p in members) / len(members),
        sum(p.lng for p in members) / len(members),
    )


def areas(pois: list[POI]) -> list[str]:
    """按出现顺序返回所有商圈，保持稳定排序方便给前端做下拉框。"""
    seen: list[str] = []
    for p in pois:
        if p.area not in seen:
            seen.append(p.area)
    return seen
