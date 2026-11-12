"""商圈两两通行时间：优先查预计算表，查不到再退回球面距离估算。

表是 `scripts/fetch_travel.py` 用高德路径规划拉下来的（20 个商圈 190 对 × 2 种方式），
存在 `data/area_travel.csv` 里跟着仓库走。这样做的三个好处：

1. 演示现场不联外网也能跑，评委 clone 下来就是完整体验；
2. 一次推荐里的两两时间从「几千次 API」变成「一次查表」；
3. 数字来自真实路网（含高架、地铁换乘），比球面距离 × 系数准得多。

表里查不到（新加的商圈、同商圈内部）时，`pair_minutes` 返回 None，
由调用方退回 `algo/geo.py: estimate_travel_minutes`，所以这个文件缺失也不会崩。
"""

from __future__ import annotations

import csv
from pathlib import Path

DEFAULT_MATRIX = Path(__file__).resolve().parent.parent / "data" / "area_travel.csv"

Pair = tuple[str, str]
_cache: dict[Pair, tuple[float | None, float | None]] | None = None


def _as_float(raw: str | None) -> float | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_matrix(path: str | Path | None = None) -> dict[Pair, tuple[float | None, float | None]]:
    """读表：(出发商圈, 到达商圈) → (驾车分钟, 公交分钟)。"""
    csv_path = Path(path) if path else DEFAULT_MATRIX
    table: dict[Pair, tuple[float | None, float | None]] = {}
    if not csv_path.exists():
        return table
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            a = (row.get("from_area") or "").strip()
            b = (row.get("to_area") or "").strip()
            if not a or not b:
                continue
            table[(a, b)] = (
                _as_float(row.get("drive_minutes")),
                _as_float(row.get("transit_minutes")),
            )
    return table


def _matrix() -> dict[Pair, tuple[float | None, float | None]]:
    global _cache
    if _cache is None:
        _cache = load_matrix()
    return _cache


def reload(path: str | Path | None = None) -> None:
    """测试用：换一张表重新加载。"""
    global _cache
    _cache = load_matrix(path)


def pair_minutes(from_area: str, to_area: str, has_car: bool) -> float | None:
    """两个商圈之间的分钟数；没数据返回 None，让调用方退回估算。"""
    if not from_area or not to_area or from_area == to_area:
        return None
    drive, transit = _matrix().get((from_area, to_area), (None, None))
    minutes = drive if has_car else transit
    # 交通过于离谱（比如同城 0 分钟）就当没有
    return minutes if minutes and minutes > 0.5 else None
