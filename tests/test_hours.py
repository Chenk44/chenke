"""营业时间：解析高德的时间串、判定「几点还开着」、以及方案会不会因此换掉。

这三件事分属不同层（数据清洗 / 算法 / 组合搜索），但都由同一条需求驱动：
「别给用户排一个到了门口才发现关门的点」。
"""

from __future__ import annotations

import csv

import pytest

from algo.combine import build_plans
from algo.loader import load_pois
from algo.types import POI, Preference
from scripts.open_hours import default_hours, parse_open_time
from tests.test_algo import make_poi

# ---------- 解析高德的时间串 ----------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("09:30-22:00", (9.5, 22.0)),
        ("08:30-11:30 13:30-17:00", (8.5, 17.0)),  # 中午休息：取包络
        ("24小时营业", (0.0, 24.0)),
        ("全天", (0.0, 24.0)),
        ("周一至周日 10:00-22:00", (10.0, 22.0)),
        ("18:00-02:00", (18.0, 26.0)),  # 跨零点：打烊记成 26 点
        ("", None),
        ("休息", None),
        ("说不清", None),
    ],
)
def test_parse_open_time(text, expected):
    assert parse_open_time(text) == expected


def test_default_hours_falls_back_to_category():
    assert default_hours("深圳湾公园", "公园") == (0.0, 24.0)
    assert default_hours("某美术馆", "展览") == (10.0, 22.0)
    # 名字里的「夜市」优先级高于品类（高德常把夜市丢进公园）
    assert default_hours("车公庙美食街夜市", "公园")[1] > 24


# ---------- POI 判定 ----------


def test_is_open_at_handles_midnight():
    bar = make_poi(open_hour=18.0, close_hour=26.0)
    assert bar.is_open_at(19.0)
    assert bar.is_open_at(1.0)  # 凌晨一点还开着
    assert not bar.is_open_at(3.0)


def test_hours_text_is_empty_for_all_day():
    assert make_poi().hours_text() == ""
    assert make_poi(open_hour=9.5, close_hour=22.0).hours_text() == "09:30-22:00"


def test_loader_defaults_to_all_day_when_columns_are_missing(tmp_path):
    """老 CSV 没有营业时间两列时，不能因为「没填」就把所有地点判成关门。"""
    src = load_pois()
    path = tmp_path / "no_hours.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "id", "name", "area", "district", "category", "lat", "lng", "avg_price",
                "rating", "indoor", "quiet", "min_people", "max_people", "kid_friendly",
                "need_booking", "queue", "tags", "blurb",
            ]
        )  # fmt: skip
        p = src[0]
        writer.writerow(
            [
                p.id, p.name, p.area, p.district, p.category, p.lat, p.lng, p.avg_price,
                p.rating, p.indoor, p.quiet, p.min_people, p.max_people, p.kid_friendly,
                p.need_booking, p.queue, "|".join(p.tags), p.blurb,
            ]
        )  # fmt: skip
    loaded = load_pois(path)
    assert loaded[0].open_hour == 0.0
    assert loaded[0].close_hour == 24.0
    assert loaded[0].is_open_at(23.5)


def test_real_dataset_has_hours_filled():
    pois = load_pois()
    filled = [p for p in pois if p.hours_text()]
    assert len(filled) > len(pois) * 0.8, "营业时间应该覆盖绝大多数地点"
    assert all(p.close_hour > p.open_hour for p in pois)


# ---------- 组合搜索里怎么用 ----------


def _consensus(pois: list[POI], score: float = 0.9):
    from algo.aggregate import Consensus

    return {
        p.id: Consensus(poi_id=p.id, consensus=score, mean=score, worst=score, worst_member="小林")
        for p in pois
    }


def _matrix(prefs: list[Preference], pois: list[POI], score: float = 0.9):
    return {p.member_id: {poi.id: score for poi in pois} for p in prefs}


def test_a_place_that_closes_early_is_flagged_when_we_start_late():
    """19 点出发、书店 21:30 关门：排到 22:40 就该被标出来。"""
    bookstore = make_poi(
        id="book", name="书店", category="展览", open_hour=9.5, close_hour=21.0, lat=22.52
    )
    cafe = make_poi(id="cafe", name="咖啡", category="咖啡", open_hour=8.0, close_hour=23.0)
    pois = [bookstore, cafe]
    prefs = [Preference(member_id="小林", start_hour=21)]
    plans = build_plans(
        pois=pois,
        prefs=prefs,
        matrix=_matrix(prefs, pois),
        consensus=_consensus(pois),
        origin=(22.518, 113.936),
        group_size=2,
        window_minutes=240,
        top_k=1,
        start_minute=21 * 60,
    )
    assert plans
    plan = plans[0]
    # 21 点出发，书店一定已经在打烊的路上
    assert "book" in plan.closed
    assert "已过营业时间" in plan.explanation


def test_a_place_open_all_day_is_never_flagged():
    park = make_poi(id="park", name="公园", category="公园", open_hour=0.0, close_hour=24.0)
    cafe = make_poi(id="cafe", name="咖啡", category="咖啡", open_hour=8.0, close_hour=23.0)
    pois = [park, cafe]
    prefs = [Preference(member_id="小林", start_hour=20)]
    plans = build_plans(
        pois=pois,
        prefs=prefs,
        matrix=_matrix(prefs, pois),
        consensus=_consensus(pois),
        origin=(22.518, 113.936),
        group_size=2,
        window_minutes=180,
        top_k=1,
        start_minute=20 * 60,
    )
    assert plans and plans[0].closed == ()
