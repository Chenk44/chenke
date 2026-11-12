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

# ---------------------------------------------------------------------------
# 否定与分句
#
# 之前的写法是「见词就置 True」，于是「不想去室内」和「要去室内」得到同一个结果。
# 这里改成：先按标点断句，每句里再看目标词前面有没有否定词。
# 条件句（「如果下雨就算了」）单独标出来——它描述的是触发条件，不是当下的约束，
# 直接当硬约束会把「不想去室内，但如果下雨就算了」读成「想去室内」。
# ---------------------------------------------------------------------------
_CLAUSE_SPLIT = re.compile(r"[，,。；;！!？?\n]+")
_CONDITIONAL = re.compile(r"如果|要是|万一|假如|的话|那就算|再说")
_NEG = re.compile(r"不想|不要|不去|不喜欢|不乐意|受不了|没兴趣|讨厌|拒绝|别|不|算了")
# 中文习惯把否定放在后面：「室内待腻了」「这地方去够了」。只看前面会漏。
_NEG_TAIL = re.compile(r"腻|受够|待够|玩够|去够|烦|厌倦|够了|受不了")
_INTENT = re.compile(r"想|要|去|吃|逛|看|玩|安排|来点")

# 室内 / 室外 信号词。只放「说的是空间」的词，不放品类词——
# 否则「不要玩桌游」会因为「桌游」被算作室内信号，把整句读成「想去室外」。
_INDOOR_WORDS = ("室内", "商场", "购物中心", "空调", "室内场")
_OUTDOOR_WORDS = ("室外", "户外", "外面", "露天", "露天场")

# 品类词：被否定就进「排除」，跟着「想/去/吃/逛」就进「偏好」。
_CATEGORY_WORDS: dict[str, tuple[str, ...]] = {
    "桌游": ("桌游", "狼人杀"),
    "密室": ("密室", "剧本杀"),
    "KTV": ("ktv", "唱歌"),
    "影院": ("电影", "影院", "影城"),
    "展览": ("展览", "美术馆", "博物馆", "看展"),
    "公园": ("公园", "爬山", "徒步", "绿道", "露营"),
    "商场": ("商场", "购物中心"),
    "咖啡": ("咖啡",),
    "火锅": ("火锅",),
    "海鲜": ("海鲜",),
}

# 体验类软约束：这些对应数据集里的 tags，不需要新字段。
_QUEUE_AVOID = re.compile(r"不想排队|别排队|不要排队|怕排队|别等位|排太久")
_PHOTO = re.compile(r"拍照|出片|打卡")
_SIT = re.compile(r"坐着|有座位|能坐|坐下来")
_CROWD_AVOID = re.compile(r"人少|别太挤|不要太挤|不挤|人别太多")

# 时长与开始时间
_DURATION_RE = re.compile(r"([一两二三四五六七八九十\d])\s*个?半?\s*小时")
_CN_NUM = {
    "一": 1,
    "两": 2,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_HALF_DAY = re.compile(r"半天")
_WHOLE_DAY = re.compile(r"一整天|全天|一整天")
_NOT_LONG = re.compile(r"别太久|不要太久|别玩太久|不用太久|时间不多")
_START_WORDS: tuple[tuple[str, int], ...] = (
    ("上午", 10),
    ("中午", 12),
    ("下午", 14),
    ("傍晚", 17),
    ("晚上", 19),
    ("夜里", 21),
)


def _split_clauses(text: str) -> list[tuple[str, bool]]:
    """按标点断句，返回 (子句, 是否条件句)。"""
    out: list[tuple[str, bool]] = []
    for raw in _CLAUSE_SPLIT.split(text):
        clause = raw.strip()
        if not clause:
            continue
        out.append((clause, bool(_CONDITIONAL.search(clause))))
    return out


def _polarity(clause: str, words: tuple[str, ...]) -> tuple[int, str]:
    """在一句里找这些词，返回 (+1 正向 / -1 被否定 / 0 没提到, 命中的词)。"""
    low = clause.casefold()
    for word in words:
        idx = low.find(word.casefold())
        if idx < 0:
            continue
        head = low[max(0, idx - 6) : idx]
        if _NEG.search(head):
            return -1, word
        tail = low[idx + len(word) : idx + len(word) + 6]
        if _NEG_TAIL.search(tail):
            return -1, word
        return 1, word
    return 0, ""


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

    # 新：室内倾向是三态。-1 想去外面 / +1 想进室内 / None 没提。
    # 之前只有一个布尔 require_indoor，False 在算法里等于「没说话」，
    # 所以用户说「不想去室内」时系统完全无动于衷。
    indoor_pref: int | None = None
    prefer_categories: list[str] = field(default_factory=list)
    exclude_categories: list[str] = field(default_factory=list)
    prefer_tags: list[str] = field(default_factory=list)
    max_minutes: int | None = None
    start_hour: int | None = None
    # 每个约束被哪段原文触发，前端标签可以 hover 显示「依据」
    evidence: dict[str, str] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return (
            self.require_indoor is None
            and self.quiet is None
            and self.price is None
            and self.near is None
            and self.with_kids is None
            and self.has_car is None
            and self.max_price is None
            and self.indoor_pref is None
            and self.max_minutes is None
            and self.start_hour is None
            and not self.exclude_tags
            and not self.prefer_categories
            and not self.exclude_categories
            and not self.prefer_tags
        )


def parse_constraints(text: str) -> ParsedHints:
    """解析一句话。纯函数，同样的输入永远给同样的输出。"""
    out = ParsedHints()
    if not text or not text.strip():
        return out

    t = text.strip()
    clauses = _split_clauses(t)
    # 条件句（「如果下雨就算了」）不参与硬约束判定，否则会把意思读反。
    focus = "，".join(clause for clause, conditional in clauses if not conditional) or t

    if _INDOOR.search(focus):
        out.require_indoor = True
        if out.indoor_pref is None:
            out.indoor_pref = 1
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
        if out.indoor_pref is None:
            out.indoor_pref = 1
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

    # --- 分句 + 否定感知的解析（「不想去室内」要读成想去外面）-------------
    for clause, conditional in clauses:
        # 室内 / 室外倾向：三态，-1 想出去，+1 想进来
        indoor_pol, _ = _polarity(clause, _INDOOR_WORDS)
        outdoor_pol, _ = _polarity(clause, _OUTDOOR_WORDS)
        want_in = indoor_pol > 0 or outdoor_pol < 0
        want_out = indoor_pol < 0 or outdoor_pol > 0

        if conditional:
            # 「如果下雨就算了」是触发条件，不是当下的要求——记一句就跳过
            if want_in:
                out.hints.append(f"条件：{clause}")
            continue

        if want_in and not want_out:
            out.indoor_pref = 1
            out.evidence.setdefault("indoor_pref", clause)
            out.hints.append("想进室内")
        elif want_out and not want_in:
            out.indoor_pref = -1
            out.evidence.setdefault("indoor_pref", clause)
            out.hints.append("想去室外")

        # 品类：被否定的进排除，跟着「想/去/吃/逛」的进偏好
        for cat, words in _CATEGORY_WORDS.items():
            pol, _ = _polarity(clause, words)
            if pol < 0:
                if cat not in out.exclude_categories:
                    out.exclude_categories.append(cat)
                    out.evidence.setdefault(f"exclude:{cat}", clause)
                    out.hints.append(f"不去「{cat}」")
            elif pol > 0 and _INTENT.search(clause) and cat not in out.prefer_categories:
                out.prefer_categories.append(cat)
                out.evidence.setdefault(f"prefer:{cat}", clause)
                out.hints.append(f"想去「{cat}」")

        # 体验类软约束，映射到数据集里已有的 tags
        if _QUEUE_AVOID.search(clause) and "排队" not in out.exclude_tags:
            out.exclude_tags.append("排队")
            out.evidence.setdefault("no_queue", clause)
            out.hints.append("不想排队")
        if _CROWD_AVOID.search(clause) and out.quiet is None:
            out.quiet = 0.85
            out.hints.append("人少一点")
        if _PHOTO.search(clause) and "拍照" not in out.prefer_tags:
            out.prefer_tags.append("拍照")
            out.hints.append("想拍照")
        if _SIT.search(clause) and "座位" not in out.prefer_tags:
            out.prefer_tags.append("座位")
            out.hints.append("要能坐着")

        # 时长与开始时间
        if _NOT_LONG.search(clause) and out.max_minutes is None:
            out.max_minutes = 180
            out.hints.append("时间别太长")
        if _HALF_DAY.search(clause) and out.max_minutes is None:
            out.max_minutes = 240
        if _WHOLE_DAY.search(clause) and out.max_minutes is None:
            out.max_minutes = 480
        m_dur = _DURATION_RE.search(clause)
        if m_dur:
            token = m_dur.group(1)
            hours = _CN_NUM.get(token) or (int(token) if token.isdigit() else 0)
            if 1 <= hours <= 12:
                out.max_minutes = hours * 60
                out.hints.append(f"最多玩 {hours} 小时")
        if out.start_hour is None:
            for word, hour in _START_WORDS:
                if word in clause:
                    out.start_hour = hour
                    out.hints.append(f"{word}出发（{hour}:00）")
                    break

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

    # 旧的布尔字段折成三态：明确说了室内就 +1；说了室外由下面的 indoor_pref 覆盖
    if hints.indoor_pref is None and hints.require_indoor:
        _set("indoor_pref", 1, sensitive=False)
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

    # 新增字段只在 base 里已经有这个键时才写。
    # 这样解析器可以先于数据库演进：PreferenceRecord 还没加列时，
    # 这些约束仍会显示在 hints 里，只是不落库，不会抛 AttributeError。
    for key, value in (
        ("indoor_pref", hints.indoor_pref),
        ("max_minutes", hints.max_minutes),
        ("start_hour", hints.start_hour),
    ):
        if key in merged:
            _set(key, value, sensitive=False)

    for key, values in (
        ("prefer_categories", hints.prefer_categories),
        ("exclude_categories", hints.exclude_categories),
        ("prefer_tags", hints.prefer_tags),
    ):
        if key not in merged or not values:
            continue
        existing = list(merged.get(key) or [])
        for value in values:
            if value not in existing:
                existing.append(value)
                result.applied.append(key)
        merged[key] = existing

    return result
