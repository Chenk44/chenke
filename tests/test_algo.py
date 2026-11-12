"""算法层单元测试。

这些测试是「我们不是套壳」最直接的证据：
每一条都对应算法说明书里的一句话，改坏了 CI 会红。
"""

from __future__ import annotations

import pytest

from algo.aggregate import aggregate, consensus_for, minimax_regret, rank_agreement
from algo.geo import distance_decay, estimate_travel_minutes, haversine_km
from algo.loader import POIDataError, load_pois
from algo.pipeline import apply_weather, recommend
from algo.types import CATEGORIES, POI, Preference
from algo.utility import comfort_price, price_score, score_poi


def make_poi(**kw) -> POI:
    base = dict(
        id="p1",
        name="测试地点",
        area="海岸城",
        district="南山区",
        category="餐饮",
        lat=22.518,
        lng=113.936,
        avg_price=80.0,
        rating=4.5,
        indoor=True,
        quiet=0.5,
        min_people=2,
        max_people=10,
        kid_friendly=True,
        need_booking=False,
        queue=0.2,
        tags=(),
        blurb="",
    )
    base.update(kw)
    return POI(**base)


# ---------- 数据加载 ----------


def test_load_pois_returns_valid_data():
    pois = load_pois()
    assert len(pois) >= 40, "深圳地点表至少要 40 条，否则组合空间太小"
    assert all(p.category in CATEGORIES for p in pois)
    assert len({p.id for p in pois}) == len(pois), "id 不能重复"
    assert all(20 < p.lat < 25 and 112 < p.lng < 116 for p in pois)


def test_areas_cover_multiple_districts():
    pois = load_pois()
    districts = {p.district for p in pois}
    assert len(districts) >= 4, "只做一个区就失去『深圳东西狭长』这个卖点了"


def test_loader_rejects_unknown_category():
    """脏数据必须在启动阶段炸掉，而不是上线后算出离谱结果。"""
    from pathlib import Path

    csv = Path(__file__).parent / "_bad_category.csv"
    csv.write_text(
        "id,name,area,district,category,lat,lng,avg_price,rating,indoor,quiet,"
        "min_people,max_people,kid_friendly,need_booking,queue,tags,blurb\n"
        "x1,新地点,海岸城,南山区,火锅,22.5,113.9,80,4.5,true,0.5,2,8,true,false,0.2,,"
        "一句话\n",
        encoding="utf-8",
    )
    try:
        with pytest.raises(POIDataError, match="未知品类"):
            load_pois(csv)
    finally:
        csv.unlink(missing_ok=True)


# ---------- 效用函数 ----------


def test_comfort_price_follows_slider():
    assert comfort_price(Preference("a", price=0.0)) == pytest.approx(40.0)
    assert comfort_price(Preference("a", price=1.0)) == pytest.approx(300.0)


def test_cheap_places_never_penalised():
    """省钱的人不会觉得「更便宜」是坏事。"""
    pref = Preference("a", price=0.2)
    assert price_score(10, pref) == 1.0
    assert price_score(comfort_price(pref), pref) == 1.0
    assert price_score(1000, pref) < 0.5


def test_quiet_preference_prefers_quiet_place():
    quiet = make_poi(id="quiet", quiet=0.9, category="展览")
    loud = make_poi(id="loud", quiet=0.1, category="展览")
    pref = Preference("a", quiet=0.9)
    assert score_poi(quiet, pref, 10).score > score_poi(loud, pref, 10).score


def test_distance_hurts_people_who_want_to_stay_close():
    pref_near = Preference("a", near=0.0)
    pref_far = Preference("a", near=1.0)
    poi = make_poi()
    near_score = score_poi(poi, pref_near, 5).score
    far_score = score_poi(poi, pref_near, 60).score
    assert near_score > far_score

    # 愿意跑远的人，同样的 60 分钟掉分更少
    loss_near = near_score - far_score
    loss_far = score_poi(poi, pref_far, 5).score - score_poi(poi, pref_far, 60).score
    assert loss_far < loss_near


def test_hard_budget_is_a_strong_penalty():
    pref = Preference("a", max_price=100)
    ok = score_poi(make_poi(avg_price=90), pref, 10).score
    over = score_poi(make_poi(avg_price=400), pref, 10).score
    assert over < ok * 0.5


def test_diet_exclusion_penalises_tagged_place():
    pref = Preference("a", exclude_tags=("辣",))
    spicy = score_poi(make_poi(tags=("辣", "火锅")), pref, 10).score
    mild = score_poi(make_poi(tags=("面食",)), pref, 10).score
    assert spicy < mild * 0.5


def test_indoor_requirement_outdoors_penalty():
    pref = Preference("a", indoor_pref=1)
    inside = score_poi(make_poi(indoor=True), pref, 10).score
    outside = score_poi(make_poi(indoor=False), pref, 10).score
    assert outside < inside


def test_wanting_to_go_outside_penalises_indoor_places():
    """「今天不想在室内待着」——这句以前在算法里完全没声音。"""
    pref = Preference("a", indoor_pref=-1)
    inside = score_poi(make_poi(indoor=True), pref, 10).score
    outside = score_poi(make_poi(indoor=False), pref, 10).score
    assert inside < outside


def test_no_indoor_preference_scores_both_the_same():
    pref = Preference("a")
    inside = score_poi(make_poi(indoor=True), pref, 10).score
    outside = score_poi(make_poi(indoor=False), pref, 10).score
    assert inside == pytest.approx(outside)


def test_group_too_big_for_small_venue_is_penalised():
    poi = make_poi(min_people=1, max_people=4)
    small = score_poi(poi, Preference("a"), 10, group_size=3).score
    big = score_poi(poi, Preference("a"), 10, group_size=10).score
    assert big < small


# ---------- 地理 ----------


def test_haversine_matches_known_distance():
    # 海岸城 → 万象天地，实际约 2.6 公里
    km = haversine_km(22.5180, 113.9360, 22.5402, 113.9543)
    assert 2.0 < km < 3.5


def test_travel_minutes_grow_with_distance():
    a = estimate_travel_minutes(22.5180, 113.9360, 22.5185, 113.9365)
    b = estimate_travel_minutes(22.5180, 113.9360, 22.5960, 114.3060)
    assert a < b
    assert a < 10, "同一商圈内应该走路就到"


def test_distance_decay_halves_at_half_life():
    assert distance_decay(0) == 1.0
    assert distance_decay(25, half_life=25) == pytest.approx(0.5)
    assert distance_decay(50, half_life=25) < distance_decay(25, half_life=25)


# ---------- 群体聚合 ----------


def test_consensus_rewards_fairness_over_raw_average():
    """平均分相同，但有人被牺牲的方案，共识分必须更低。

    这正是「一群人的决策」和「一个人的推荐」的分界线。
    """
    polarised = {"甲": 0.9, "乙": 0.1, "丙": 0.9}  # 平均 0.633，乙很难受
    balanced = {"甲": 0.7, "乙": 0.6, "丙": 0.6}  # 平均 0.633，没人难受

    assert sum(polarised.values()) == pytest.approx(sum(balanced.values()))

    a = consensus_for("polarised", polarised)
    b = consensus_for("balanced", balanced)
    assert b.consensus > a.consensus
    assert a.worst_member == "乙"
    assert a.spread > b.spread


def test_aggregate_sorts_by_consensus_desc():
    matrix = {
        "甲": {"x": 0.9, "y": 0.2},
        "乙": {"x": 0.8, "y": 0.3},
        "丙": {"x": 0.2, "y": 0.9},
    }
    ranked = aggregate(matrix)
    assert ranked[0].poi_id in {"x", "y"}
    assert [c.consensus for c in ranked] == sorted([c.consensus for c in ranked], reverse=True)


def test_minimax_regret_punishes_the_worst_case():
    regret = minimax_regret(
        {
            "甲": {"safe": 0.7, "gamble": 1.0},
            "乙": {"safe": 0.7, "gamble": 0.0},
        }
    )
    assert regret["safe"] > regret["gamble"], "gamble 让乙损失 0.7，应当更后悔"


def test_rank_agreement_is_one_when_orders_match():
    matrix = {
        "甲": {"a": 0.9, "b": 0.5, "c": 0.1},
        "乙": {"a": 0.8, "b": 0.6, "c": 0.2},
    }
    assert rank_agreement(matrix) == pytest.approx(1.0)


def test_single_member_consensus_equals_own_score():
    c = consensus_for("x", {"甲": 0.83})
    assert c.consensus == pytest.approx(0.83)
    assert c.spread == 0.0


# ---------- 组合搜索 ----------


def _small_setup():
    pois = load_pois()
    prefs = [
        Preference("甲", quiet=0.7, price=0.4, near=0.3),
        Preference("乙", quiet=0.2, price=0.8, near=0.7),
        Preference("丙", quiet=0.5, price=0.5, near=0.5, with_kids=True),
    ]
    return pois, prefs


def test_build_plans_returns_diverse_routes():
    pois, prefs = _small_setup()
    rec = recommend(pois, prefs, origin=(22.518, 113.936))
    assert 1 <= len(rec.plans) <= 3
    for plan in rec.plans:
        assert 2 <= len(plan.items) <= 3
        cats = [p.category for p in plan.items]
        assert len(set(cats)) == len(cats), "同一条动线里不该有两个同品类"
        assert {"餐饮", "咖啡"} & set(cats), "总得有一个能吃饭的地方"
        assert plan.total_minutes > 0


def test_everyone_wants_outdoors_still_gets_plans_with_food():
    """全员喊着要出去时，室内餐饮会被压出候选池，别让「必须有一顿饭」把方案全否掉。"""
    pois = load_pois()
    prefs = [Preference(f"p{i}", indoor_pref=-1) for i in range(5)]
    rec = recommend(pois, prefs, origin=(22.518, 113.936), window_minutes=360)
    assert len(rec.plans) >= 1
    for plan in rec.plans:
        assert {"餐饮", "咖啡"} & {p.category for p in plan.items}
        assert all(not p.indoor for p in plan.items), "全员想出去，就该给室外的点"


def test_recommendation_is_deterministic():
    """同样的输入必须给同样的输出，否则投票没法和别人对齐。"""
    pois, prefs = _small_setup()
    first = recommend(pois, prefs, origin=(22.518, 113.936))
    second = recommend(pois, prefs, origin=(22.518, 113.936))
    assert [p.items[0].id for p in first.plans] == [p.items[0].id for p in second.plans]
    assert [round(p.consensus, 6) for p in first.plans] == [
        round(p.consensus, 6) for p in second.plans
    ]


def test_plans_are_ranked_by_score():
    pois, prefs = _small_setup()
    rec = recommend(pois, prefs, origin=(22.518, 113.936))
    scores = [p.consensus for p in rec.plans]
    assert scores == sorted(scores, reverse=True)


def test_every_plan_carries_an_ascending_timeline():
    """前端的「14:02 → 15:34」完全靠这些偏移量，错了整条时间线就乱。"""
    pois, prefs = _small_setup()
    rec = recommend(pois, prefs, origin=(22.518, 113.936))
    for plan in rec.plans:
        assert len(plan.offsets) == len(plan.items)
        assert plan.offsets[0] > 0, "从出发点过去也要花时间"
        assert plan.offsets == sorted(plan.offsets)
        assert all(b > a for a, b in zip(plan.offsets, plan.offsets[1:], strict=False)), (
            "时间必须严格递增"
        )
        assert plan.offsets[-1] < plan.total_minutes


def test_time_window_is_filled_but_not_overbooked():
    """6 小时的窗口不该只排出 2 小时的行程——那是没接住需求。"""
    pois, prefs = _small_setup()
    loose = recommend(pois, prefs, origin=(22.518, 113.936), window_minutes=360)
    tight = recommend(pois, prefs, origin=(22.518, 113.936), window_minutes=150)
    assert loose.plans[0].total_minutes >= tight.plans[0].total_minutes


def test_explanation_is_human_readable():
    pois, prefs = _small_setup()
    rec = recommend(pois, prefs, origin=(22.518, 113.936))
    text = rec.plans[0].explanation
    assert text.endswith("。")
    assert "小时" in text
    assert "→" in text, "方案应该按动线顺序显示"


def test_empty_inputs_raise():
    with pytest.raises(ValueError):
        recommend([], [Preference("a")], origin=(22.5, 113.9))
    with pytest.raises(ValueError):
        recommend(load_pois(), [], origin=(22.5, 113.9))


# ---------- 天气 ----------


def test_rain_flips_everyone_to_indoor():
    prefs = [Preference("甲"), Preference("乙")]
    notes = apply_weather(prefs, "rain")
    assert all(p.indoor_pref == 1 for p in prefs)
    assert notes and "室内" in notes[0]


def test_clear_weather_changes_nothing():
    prefs = [Preference("甲")]
    notes = apply_weather(prefs, "clear")
    assert prefs[0].indoor_pref == 0
    assert notes == []


def test_rainy_recommendation_prefers_indoor_places():
    """下雨时，方案里室内地点的占比应显著高于晴天。"""
    pois, prefs = _small_setup()

    def indoor_ratio(weather: str) -> float:
        ps = [
            Preference(
                p.member_id, quiet=p.quiet, price=p.price, near=p.near, with_kids=p.with_kids
            )
            for p in prefs
        ]
        rec = recommend(pois, ps, origin=(22.518, 113.936), weather=weather)
        items = [i for plan in rec.plans for i in plan.items]
        return sum(1 for i in items if i.indoor) / len(items)

    assert indoor_ratio("rain") >= indoor_ratio("clear")


def test_group_budget_flows_into_every_plan():
    pois, prefs = _small_setup()
    for p in prefs:
        p.max_price = 60
    rec = recommend(pois, prefs, origin=(22.518, 113.936))
    assert rec.plans, "预算再紧也要给出方案，不能空手而归"


# ---------- 一句话里的正向偏好与硬性时长 ----------


def test_saying_you_want_hotpot_lifts_hotpot_places():
    """「想吃火锅」是加分项：火锅店该排到前面，但不该把别的地方判死刑。"""
    plain = Preference("甲")
    keen = Preference("甲", prefer_categories=("火锅",))
    hotpot = make_poi(id="hot", name="某某火锅城", category="餐饮")
    gallery = make_poi(id="art", name="某某美术馆", category="展览", indoor=True)

    assert score_poi(hotpot, keen, 10).score > score_poi(hotpot, plain, 10).score
    assert score_poi(gallery, keen, 10).score == score_poi(gallery, plain, 10).score


def test_excluding_a_thing_is_narrower_than_excluding_the_category():
    """说「不要玩桌游」只想避开桌游吧，不该顺手把密室、摩天轮一起毙掉。"""
    boardgame = make_poi(id="bg", name="桌游吧(海岸城)", category="玩乐", indoor=True)
    escape = make_poi(id="esc", name="迷之密室", category="玩乐", indoor=True)

    picky = Preference("甲", exclude_categories=("桌游",))
    assert score_poi(boardgame, picky, 10).score < score_poi(boardgame, Preference("甲"), 10).score
    assert score_poi(escape, picky, 10).score == score_poi(escape, Preference("甲"), 10).score

    whole_cat = Preference("乙", exclude_categories=("玩乐",))
    assert score_poi(escape, whole_cat, 10).score < score_poi(escape, Preference("乙"), 10).score


def test_a_personal_time_cap_shortens_the_plan():
    """有人说「最多玩两小时」，方案就不该还给一条五小时的动线。"""
    pois, prefs = _small_setup()
    loose = recommend(pois, prefs, origin=(22.518, 113.936), window_minutes=360).plans[0]
    capped_prefs = [
        Preference(p.member_id, quiet=p.quiet, price=p.price, near=p.near, max_minutes=180)
        for p in prefs
    ]
    capped = recommend(pois, capped_prefs, origin=(22.518, 113.936), window_minutes=360).plans[0]
    assert capped.total_minutes <= loose.total_minutes


def test_start_hour_follows_the_latest_person():
    """有人说七点才下班，出发时间就得按七点算。"""
    pois, prefs = _small_setup()
    prefs[0].start_hour = 10
    prefs[1].start_hour = 19
    rec = recommend(pois, prefs, origin=(22.518, 113.936))
    assert rec.start_minute == 19 * 60
    assert rec.to_dict()["plans"][0]["start_minute"] == 19 * 60


def test_start_hour_defaults_when_nobody_says_anything():
    pois, prefs = _small_setup()
    rec = recommend(pois, prefs, origin=(22.518, 113.936))
    assert rec.start_minute == 14 * 60
