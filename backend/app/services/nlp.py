"""把「一句话」解析成结构化约束。

这里刻意**不用大模型**：
1. 规则可测。每一条规则都有单元测试，结果 100% 可复现，答辩现场断网也能演示；
2. 解析只要 3 毫秒，用户在滑杆上拖动时能实时反馈；
3. 语义解析的失败模式是「漏识别」，而不是「胡说八道」——漏了用户可以自己补滑杆，
   胡说八道会让用户对整个产品失去信任。

如果以后接入大模型，正确做法是：让模型输出下面这个 ParsedHints 结构，
规则版本作为兜底和交叉校验，而不是让模型直接决定推荐结果。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 数字 + 单位，用于抓「人均 100」「一百块左右」
_PRICE_RE = re.compile(r"(?:人均|每个人|一人|预算)?\s*(\d{2,4})\s*(?:块|元|rmb|左右|以内)")

# 餐厅类别 → 忌口标签（只处理表里真实存在的标签，避免误伤）
_DIET_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?:不|别|不能|不要|怕)吃辣|不能吃辣|怕辣|不要辣|微辣都不行|无辣|忌辣"), "辣"),
    (re.compile(r"(不吃|不能吃|过敏).{0,4}海鲜|海鲜过敏"), "海鲜"),
    (re.compile(r"(不吃|不能吃).{0,4}火锅"), "火锅"),
    (re.compile(r"(不吃|不能吃).{0,4}烧烤"), "烧烤"),
    (re.compile(r"素食|吃素"), "肉"),
)

_INDOOR = re.compile(r"下雨|雨天|暴雨|台风|太晒|晒死|热死|高温|好热|怕热|下雪")
_QUIET = re.compile(r"安静|不吵|清净|别太吵|说话都费劲|耳鸣")
_LOUD = re.compile(r"热闹|嗨一点|蹦迪|人多才好玩|气氛")
_SAVE = re.compile(r"省钱|便宜|实惠|穷|学生党|不要超过|预算有限|抠")
_SPLURGE = re.compile(r"随便花|不差钱|贵点没事|舍得|吃好点")
_NEAR = re.compile(r"就近|别走远|太远|楼下|附近|腿懒|不想坐车")
_FAR = re.compile(r"远一点|跑远|海边|爬山|大鹏|愿意跑")
_KIDS = re.compile(r"带娃|孩子|小孩|小朋友|宝宝")
_CAR = re.compile(r"开车|自驾|有车")


@dataclass
class ParsedHints:
    """从一句话里读出来的约束。字段为 None 表示「这句话没提到」。"""

    require_indoor: bool | None = None
    quiet: float | None = None
    price: float | None = None
    near: float | None = None
    with_kids: bool | None = None
    has_car: bool | None = None
    max_price: float | None = None
    exclude_tags: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return (
            self.require_indoor is None
            and self.quiet is None
            and self.price is None
            and self.near is None
            and self.with_kids is None
            and self.has_car is None
            and self.max_price is None
            and not self.exclude_tags
        )


def parse_constraints(text: str) -> ParsedHints:
    """解析一句话。纯函数，同样的输入永远给同样的输出。"""
    out = ParsedHints()
    if not text or not text.strip():
        return out

    t = text.strip()

    if _INDOOR.search(t):
        out.require_indoor = True
        out.hints.append("优先室内（下雨/高温）")

    if _QUIET.search(t) and not _LOUD.search(t):
        out.quiet = 0.8
        out.hints.append("想安静")
    elif _LOUD.search(t) and not _QUIET.search(t):
        out.quiet = 0.2
        out.hints.append("想热闹")

    if _SAVE.search(t) and not _SPLURGE.search(t):
        out.price = 0.2
        out.hints.append("想省钱")
    elif _SPLURGE.search(t) and not _SAVE.search(t):
        out.price = 0.85
        out.hints.append("愿意花钱")

    if _NEAR.search(t) and not _FAR.search(t):
        out.near = 0.2
        out.hints.append("不想跑远")
    elif _FAR.search(t) and not _NEAR.search(t):
        out.near = 0.85
        out.hints.append("愿意跑远")

    if _KIDS.search(t):
        out.with_kids = True
        out.require_indoor = True
        out.hints.append("带孩子，优先室内")

    if _CAR.search(t):
        out.has_car = True
        out.hints.append("自驾出行")

    for pattern, tag in _DIET_RULES:
        if pattern.search(t) and tag not in out.exclude_tags:
            out.exclude_tags.append(tag)
            out.hints.append(f"避开「{tag}」")

    m = _PRICE_RE.search(t)
    if m:
        value = float(m.group(1))
        if 10 <= value <= 3000:
            out.max_price = value
            out.hints.append(f"人均不超过 {value:.0f} 元")

    return out


@dataclass
class MergeResult:
    """合并结果：最终的偏好值、被改动的字段、给用户看的解释。"""

    values: dict
    applied: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)


def merge_hints(base: dict, hints: ParsedHints) -> MergeResult:
    """把解析结果合并进用户手动填的偏好。

    原则：**用户手填的值优先于文字解析**。只有用户没动过的滑杆（仍为 0.5）
    才允许被文字覆盖，避免「我明明拖到了 0.9，又被一句话改回去」。
    """
    merged = dict(base)
    result = MergeResult(values=merged, hints=list(hints.hints))

    def _set(key: str, value, sensitive: bool = True) -> None:
        if value is None:
            return
        if sensitive and merged.get(key) not in (None, 0.5):
            return  # 用户已经手动设过，尊重用户
        merged[key] = value
        result.applied.append(key)

    _set("require_indoor", hints.require_indoor, sensitive=False)
    _set("with_kids", hints.with_kids, sensitive=False)
    _set("has_car", hints.has_car, sensitive=False)
    _set("quiet", hints.quiet)
    _set("price", hints.price)
    _set("near", hints.near)
    if hints.max_price is not None and merged.get("max_price") is None:
        merged["max_price"] = hints.max_price
        result.applied.append("max_price")

    if hints.exclude_tags:
        existing = list(merged.get("exclude_tags") or [])
        for tag in hints.exclude_tags:
            if tag not in existing:
                existing.append(tag)
                result.applied.append("exclude_tags")
        merged["exclude_tags"] = existing

    return result
