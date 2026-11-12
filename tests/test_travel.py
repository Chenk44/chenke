"""商圈通行时间表：查得到就用真数据，查不到必须安静地退回估算。"""

from __future__ import annotations

from pathlib import Path

import pytest

from algo import travel
from algo.geo import estimate_travel_minutes

SAMPLE = """from_area,to_area,drive_minutes,transit_minutes
海岸城,后海,10.2,36.6
后海,海岸城,10.5,37.0
海岸城,大鹏,95.0,
"""


@pytest.fixture
def matrix(tmp_path: Path) -> Path:
    path = tmp_path / "area_travel.csv"
    path.write_text(SAMPLE, encoding="utf-8")
    travel.reload(path)
    yield path
    travel.reload()  # 还原成仓库里那张表，别污染别的测试


def test_drive_and_transit_are_different_numbers(matrix):
    assert travel.pair_minutes("海岸城", "后海", has_car=True) == 10.2
    assert travel.pair_minutes("海岸城", "后海", has_car=False) == 36.6


def test_missing_transit_falls_back_to_none(matrix):
    assert travel.pair_minutes("海岸城", "大鹏", has_car=True) == 95.0
    assert travel.pair_minutes("海岸城", "大鹏", has_car=False) is None


def test_unknown_or_same_area_returns_none(matrix):
    assert travel.pair_minutes("海岸城", "海岸城", has_car=True) is None
    assert travel.pair_minutes("海岸城", "不存在的商圈", has_car=True) is None


def test_real_matrix_ships_with_the_repo():
    """表要跟着仓库走，否则评委 clone 下来就退回估算，等于白做。"""
    travel.reload()
    table = travel.load_matrix()
    assert len(table) >= 100, f"表里只有 {len(table)} 条，像是没提交"
    minutes = travel.pair_minutes("海岸城", "后海", has_car=False)
    assert minutes is not None and 5 < minutes < 120


def test_fallback_estimate_is_still_sane(matrix):
    """查不到商圈时用球面距离估算，数量级不能离谱。"""
    minutes = estimate_travel_minutes(113.93, 22.51, 113.95, 22.54, has_car=False)
    assert 5 < minutes < 90
