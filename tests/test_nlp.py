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
