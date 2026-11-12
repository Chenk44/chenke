"""单人对单个地点的效用函数 U(u, p)。

设计原则：
1. 每一项都能翻译成人话（评分、安静度、价格、距离、排队、带娃），
   拒绝黑箱加权，答辩时每一项都讲得出来。
2. 硬约束（忌口、预算、室内）用强惩罚而不是直接过滤，
   这样即使约束很苛刻，算法仍能给出「最不坏」的方案并解释原因。
3. 距离的衰减速度由用户自己的「愿意跑多远」决定，
   而不是所有人共用一条曲线。
"""

from __future__ import annotations

from .geo import distance_decay
from .types import POI, Preference, ScoredPOI

WEIGHTS = {
    "rating": 0.20,
    "quiet": 0.18,
    "price": 0.20,
    "distance": 0.30,
    "queue": 0.06,
    "kids": 0.06,
}

# 硬约束被违反时的乘数。0.2 意味着「除非没有别的选择，否则不选它」。
HARD_PENALTY = 0.2


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def comfort_price(pref: Preference) -> float:
    """这个人觉得「舒服」的人均价位。

    price 滑杆 0 → 40 元（学生党），1 → 300 元（舍得花）。
    """
    return 40.0 + 260.0 * _clip(pref.price)


def rating_score(rating: float) -> float:
    """3.5 分以下记 0，5.0 分记 1。低分不做过多的区分。"""
    return _clip((rating - 3.5) / 1.5)


def price_score(price: float, pref: Preference) -> float:
    """低于心理价位永远不扣分；超出后线性衰减，到 2.5 倍归零。

    这样「省钱的人去便宜的地方」和「舍得的人去贵的地方」都能拿满分，
    而不是简单地「越便宜越好」。
    """
    ideal = comfort_price(pref)
    if price <= ideal:
        return 1.0
    return _clip(1.0 - (price - ideal) / (ideal * 1.5))


def quiet_score(poi: POI, pref: Preference) -> float:
    return _clip(1.0 - abs(poi.quiet - pref.quiet))


def distance_score(minutes: float, pref: Preference) -> float:
    """愿意跑远的人，距离衰减得慢；只想在楼下的人，20 分钟就开始心疼。"""
    half_life = 15.0 + 25.0 * _clip(pref.near)
    return distance_decay(minutes, half_life=half_life)


def people_fit(poi: POI, group_size: int) -> float:
    """场地容量是否装得下这一群人。"""
    if poi.min_people <= group_size <= poi.max_people:
        return 1.0
    if group_size < poi.min_people:
        # 人太少，比如 6 人起订的包间
        return _clip(1.0 - (poi.min_people - group_size) * 0.25)
    return _clip(1.0 - (group_size - poi.max_people) * 0.15)


def score_poi(
    poi: POI,
    pref: Preference,
    travel_minutes: float,
    group_size: int = 2,
) -> ScoredPOI:
    """计算一个人对一个地点的满意度（0~1），并保留各分项。"""
    parts: dict[str, float] = {}

    parts["评分"] = WEIGHTS["rating"] * rating_score(poi.rating)
    parts["安静度"] = WEIGHTS["quiet"] * quiet_score(poi, pref)
    parts["价格"] = WEIGHTS["price"] * price_score(poi.avg_price, pref)
    parts["距离"] = WEIGHTS["distance"] * distance_score(travel_minutes, pref)
    parts["排队"] = WEIGHTS["queue"] * _clip(1.0 - poi.queue)

    if pref.with_kids:
        parts["带娃"] = WEIGHTS["kids"] * (1.0 if poi.kid_friendly else 0.0)

    score = sum(parts.values())
    penalty_reasons: list[str] = []

    # 容量
    cap = people_fit(poi, group_size)
    if cap < 1.0:
        parts["容量"] = -0.10 * (1.0 - cap)
        score += parts["容量"]
        penalty_reasons.append("人多坐不下")

    # 硬约束：忌口
    if pref.exclude_tags and poi.has_any_tag(pref.hard_tags()):
        score *= HARD_PENALTY
        penalty_reasons.append("有忌口食材")

    # 硬约束：预算上限
    if pref.max_price is not None and poi.avg_price > pref.max_price:
        score *= HARD_PENALTY
        penalty_reasons.append("超预算")

    # 硬约束：室内外偏好，两个方向都要罚。
    # 说「想待室内」（下雨、太晒、带婴儿）时罚室外，
    # 说「不想去室内」（待腻了、想出去走走）时同样罚室内——
    # 之前只有前一半，所以「所有人都说不想去室内」照样推室内。
    if pref.indoor_pref > 0 and not poi.indoor:
        score *= HARD_PENALTY
        penalty_reasons.append("在室外")
    elif pref.indoor_pref < 0 and poi.indoor:
        score *= HARD_PENALTY
        penalty_reasons.append("在室内")

    if penalty_reasons:
        parts["硬约束"] = -0.15 * len(penalty_reasons)

    return ScoredPOI(
        poi=poi,
        score=_clip(score),
        travel_minutes=travel_minutes,
        parts=parts,
    )


def score_all(
    pois: list[POI],
    pref: Preference,
    travel_fn,
    group_size: int = 2,
) -> dict[str, ScoredPOI]:
    """对一批地点打分。travel_fn(poi) 返回从出发点过去需要多少分钟。"""
    return {p.id: score_poi(p, pref, travel_fn(p), group_size) for p in pois}


def borda_points(ranking: list[str]) -> dict[str, float]:
    """Borda 计数：第 1 名得 n-1 分，最后一名得 0 分。

    用来做「只比较相对名次」的聚合，和绝对分数互为校验。
    """
    n = len(ranking)
    return {pid: float(n - 1 - i) for i, pid in enumerate(ranking)}
