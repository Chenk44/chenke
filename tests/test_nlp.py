"""一句话解析的规则测试。

规则解析的好处就是这里：每条规则都能被钉死，改坏了立刻知道。
"""

from __future__ import annotations

import pytest
from app.services.nlp import merge_hints, parse_constraints


@pytest.mark.parametrize(
    "text, field, expected",
    [
        ("下雨天去哪都行就是别淋着", "require_indoor", True),
        ("太晒了，找个有空调的", "require_indoor", True),
        ("想找个安静的地方坐坐", "quiet", 0.8),
        ("人太少没意思，要热闹", "quiet", 0.2),
        ("学生党，能省则省", "price", 0.2),
        ("今天不差钱，吃好点", "price", 0.85),
        ("别走太远，我腿懒", "near", 0.2),
        ("愿意跑远一点，去海边也行", "near", 0.85),
        ("带娃，得找能推婴儿车的", "with_kids", True),
        ("我开车，可以接人", "has_car", True),
    ],
)
def test_single_constraint(text, field, expected):
    parsed = parse_constraints(text)
    assert getattr(parsed, field) == expected


def test_budget_is_extracted():
    assert parse_constraints("人均 100 左右").max_price == 100
    assert parse_constraints("预算 60 以内吧").max_price == 60


def test_diet_tags():
    assert "辣" in parse_constraints("我不吃辣").exclude_tags
    assert "海鲜" in parse_constraints("海鲜过敏").exclude_tags
    assert "辣" not in parse_constraints("来点辣的").exclude_tags, "『要辣』不是忌口"


def test_empty_text_returns_nothing():
    assert parse_constraints("").is_empty()
    assert parse_constraints("   ").is_empty()


def test_quiet_and_loud_together_does_not_flip_flop():
    """同时出现『安静』和『热闹』时，宁可不判断，也不要乱猜。"""
    parsed = parse_constraints("安静和热闹都行")
    assert parsed.quiet is None


def test_merge_respects_manual_slider():
    base = {"quiet": 0.9, "price": 0.5, "near": 0.5, "exclude_tags": []}
    result = merge_hints(base, parse_constraints("想安静点，还想省钱"))
    assert result.values["quiet"] == 0.9, "手动值不能被覆盖"
    assert result.values["price"] == 0.2, "没动过的滑杆可以被解析结果填充"
    assert "price" in result.applied
    assert "quiet" not in result.applied


def test_merge_accumulates_exclusions():
    base = {"quiet": 0.5, "price": 0.5, "near": 0.5, "exclude_tags": ["辣"]}
    result = merge_hints(base, parse_constraints("海鲜过敏"))
    assert result.values["exclude_tags"] == ["辣", "海鲜"]


def test_merge_never_duplicates_tags():
    base = {"quiet": 0.5, "price": 0.5, "near": 0.5, "exclude_tags": ["辣"]}
    result = merge_hints(base, parse_constraints("不吃辣"))
    assert result.values["exclude_tags"] == ["辣"]


# ---------------------------------------------------------------------------
# 否定：用户说「不想去室内」，系统必须理解为「想去外面」
#
# 这一组测试是补一个真实 bug 的漏洞：以前 nlp.py 见词就置 True，
# 「不想去室内」被读成 require_indoor=True，而 require_indoor=False 在算法里
# 又等于什么都没说，于是用户越说「不想」，推荐越全是室内。
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "不想去室内",
        "别去室内，想走走",
        "今天不想在室内待着",
        "室内待腻了，想出去",
    ],
)
def test_negative_indoor_means_go_outside(text):
    assert parse_constraints(text).indoor_pref == -1


def test_positive_indoor():
    assert parse_constraints("太热了，要室内").indoor_pref == 1
    assert parse_constraints("可以去商场").indoor_pref == 1


def test_negative_outdoor_flips_to_indoor():
    assert parse_constraints("不想去户外").indoor_pref == 1


def test_conditional_clause_does_not_invert_meaning():
    """「不想去室内，但如果下雨就算了」—— 条件句不该把意思读反。"""
    parsed = parse_constraints("不想去室内，但如果下雨就算了")
    assert parsed.indoor_pref == -1
    assert parsed.require_indoor is None, "条件句里的「下雨」不该变成硬约束"


def test_negated_category_is_excluded_not_indoor():
    """「不要玩桌游」= 排除桌游，不等于「想去室外」。"""
    parsed = parse_constraints("不要玩桌游，别去密室")
    assert set(parsed.exclude_categories) == {"桌游", "密室"}
    assert parsed.indoor_pref is None


def test_mixed_sentence_keeps_both_meanings():
    parsed = parse_constraints("可以去商场，不要玩桌游")
    assert parsed.indoor_pref == 1
    assert parsed.exclude_categories == ["桌游"]
    assert "商场" in parsed.prefer_categories


def test_duration_and_start_hour():
    assert parse_constraints("两三个小时就行").max_minutes == 180
    assert parse_constraints("别玩太久").max_minutes == 180
    assert parse_constraints("晚上出发").start_hour == 19
    assert parse_constraints("下午去").start_hour == 14


def test_soft_experience_constraints():
    assert "排队" in parse_constraints("不想排队").exclude_tags
    assert "拍照" in parse_constraints("想找个能拍照的").prefer_tags
    assert "座位" in parse_constraints("要能坐着聊天").prefer_tags


def test_new_fields_only_merge_when_schema_has_them():
    """数据库还没加 indoor_pref 列时，解析结果只出现在 hints 里，不能炸。"""
    base = {"quiet": 0.5, "price": 0.5, "near": 0.5, "exclude_tags": []}
    result = merge_hints(base, parse_constraints("不想去室内"))
    assert "indoor_pref" not in result.values
    assert any("室外" in h for h in result.hints)

    base2 = {**base, "indoor_pref": None}
    result2 = merge_hints(base2, parse_constraints("不想去室内"))
    assert result2.values["indoor_pref"] == -1
    assert "indoor_pref" in result2.applied
