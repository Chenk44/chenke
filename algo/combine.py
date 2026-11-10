"""方案组合搜索：把「推荐一个地点」升级成「推荐一条动线」。

一个方案的形态是 2~3 个地点按顺序连起来，例如：
    下午 2 点 咖啡 → 4 点 看展 → 6 点半 吃饭

搜索策略是「先剪枝再穷举」，而不是遗传算法：
    - 先用共识分把候选池从几百个砍到 24 个；
    - 24 选 3 只有 2024 种，每种再试 6 种顺序，总量约 1.2 万，
      单次计算在毫秒级。
    - 这个规模上，穷举是全局最优的；上启发式算法反而引入调参风险，
      也失去了「结果可复现」这个答辩时很好用的性质。
"""

from __future__ import annotations

from itertools import combinations, permutations

from .geo import estimate_travel_minutes
from .types import POI, Plan, Preference

# 每个品类的典型停留时长（分钟）
DWELL = {
    "咖啡": 60,
    "展览": 90,
    "公园": 75,
    "餐饮": 90,
    "影院": 120,
    "夜生活": 90,
    "玩乐": 90,
}

# 方案里必须至少包含一个「能填肚子」的品类
FOOD_CATEGORIES = {"餐饮", "咖啡"}

# 每多花 1 小时在路上，扣多少分
ROUTE_PENALTY_PER_HOUR = 0.10

# 时间窗太空也扣分：用户说「玩 6 小时」，你只给 3 小时的安排，是没接住需求
UNDERFILL_PENALTY = 0.15

MAX_ITEMS = 3
MIN_ITEMS = 2


def _travel(a: POI, b: POI, has_car: bool) -> float:
    return estimate_travel_minutes(a.lat, a.lng, b.lat, b.lng, has_car=has_car)


def _route_minutes(seq: tuple[POI, ...], origin: tuple[float, float], has_car: bool) -> float:
    """起点 → 第一个地点 → 第二个 …… 的总通行时间（分钟）。"""
    total = 0.0
    lat, lng = origin
    prev_lat, prev_lng = lat, lng
    for poi in seq:
        total += estimate_travel_minutes(prev_lat, prev_lng, poi.lat, poi.lng, has_car=has_car)
        prev_lat, prev_lng = poi.lat, poi.lng
    return total


def _explain(
    seq: tuple[POI, ...],
    per_member: dict[str, float],
    prefs: list[Preference],
    total_minutes: float,
) -> str:
    """用规则拼一句人话解释，而不是让大模型编。

    规则解释的好处：100% 忠于算法实际算的东西，不会出现「解释说在室内但地点在室外」。
    """
    names = " → ".join(p.name for p in seq)
    worst_member = min(per_member, key=lambda k: per_member[k]) if per_member else ""
    worst_score = per_member.get(worst_member, 0.0)
    best_score = max(per_member.values()) if per_member else 0.0

    bits = [f"{names}"]
    if len(per_member) > 1:
        bits.append(
            f"全员满意度 {min(per_member.values()):.2f}~{best_score:.2f}，"
            f"最让步的是 {worst_member}（{worst_score:.2f}）"
        )
    bits.append(f"全程约 {total_minutes / 60:.1f} 小时")

    # 挑一个最有说服力的共同约束
    indoor_all = all(p.indoor for p in seq)
    if indoor_all and any(p.require_indoor for p in prefs):
        bits.append("全程室内，下雨也不怕")
    if all(p.kid_friendly for p in seq) and any(p.with_kids for p in prefs):
        bits.append("每个点都能带娃")
    cheap = max((p.avg_price for p in seq), default=0)
    if cheap and all(p.max_price is None or cheap <= p.max_price for p in prefs):
        bits.append(f"最贵一餐人均 {cheap:.0f} 元，不超预算")

    return "；".join(bits) + "。"


def build_plans(
    pois: list[POI],
    prefs: list[Preference],
    matrix: dict[str, dict[str, float]],
    consensus: dict[str, "Consensus"],  # noqa: F821 - 避免循环导入
    origin: tuple[float, float],
    group_size: int,
    window_minutes: float = 360.0,
    top_k: int = 3,
    pool_size: int = 24,
) -> list[Plan]:
    """返回按综合分排序的 top_k 个方案。"""
    if not pois or not prefs:
        return []

    has_car = any(p.has_car for p in prefs)

    # 1) 剪枝：只保留共识分最高的 pool_size 个地点作为候选
    ranked_ids = sorted(consensus, key=lambda pid: consensus[pid].consensus, reverse=True)
    pool_ids = ranked_ids[:pool_size]
    by_id = {p.id: p for p in pois}
    pool = [by_id[pid] for pid in pool_ids if pid in by_id]

    if len(pool) < MIN_ITEMS:
        return []

    # 2) 预计算候选池内部两两通行时间，避免在循环里反复算
    pair: dict[tuple[str, str], float] = {}
    for a in pool:
        for b in pool:
            if a.id != b.id:
                pair[(a.id, b.id)] = _travel(a, b, has_car)

    origin_leg = {
        p.id: estimate_travel_minutes(origin[0], origin[1], p.lat, p.lng, has_car=has_car)
        for p in pool
    }

    candidates: list[tuple[float, tuple[POI, ...], float, dict[str, float], list[float]]] = []

    for size in range(MIN_ITEMS, MAX_ITEMS + 1):
        for combo in combinations(pool, size):
            # 品类不能重复，保证体验多样
            cats = [p.category for p in combo]
            if len(set(cats)) != len(cats):
                continue
            # 吃饭是刚需
            if not (set(cats) & FOOD_CATEGORIES):
                continue

            base = sum(consensus[p.id].consensus for p in combo) / len(combo)

            best_for_combo: tuple[float, tuple[POI, ...], float, list[float]] | None = None
            for seq in permutations(combo):
                # 逐个地点累加：什么时候到、待多久、再花多少分钟到下一个
                clock = origin_leg[seq[0].id]
                offsets = [clock]
                for i in range(len(seq) - 1):
                    clock += DWELL.get(seq[i].category, 60)
                    clock += pair[(seq[i].id, seq[i + 1].id)]
                    offsets.append(clock)

                route = origin_leg[seq[0].id] + sum(
                    pair[(seq[i].id, seq[i + 1].id)] for i in range(len(seq) - 1)
                )
                dwell = sum(DWELL.get(p.category, 60) for p in seq)
                total = route + dwell

                dwell_penalty = 0.0 if total <= window_minutes else (total - window_minutes) / 120.0
                # 时间窗太空也扣分：说好玩 6 小时，只安排 3 小时等于没接住需求
                shortfall = max(0.0, window_minutes - total) / max(window_minutes, 1.0)
                score = (
                    base
                    - ROUTE_PENALTY_PER_HOUR * (route / 60.0)
                    - dwell_penalty
                    - UNDERFILL_PENALTY * shortfall
                )
                if best_for_combo is None or score > best_for_combo[0]:
                    best_for_combo = (score, seq, total, offsets)

            if best_for_combo is None:
                continue
            score, seq, total, offsets = best_for_combo
            per_member = {m: sum(matrix[m][p.id] for p in seq) / len(seq) for m in matrix}
            candidates.append((score, seq, total, per_member, offsets))

    if not candidates:
        return []

    candidates.sort(key=lambda c: c[0], reverse=True)

    # 3) 选方案时做多样性去重：三个方案如果前两个地点都一样，对决策没有帮助。
    #    优先选和已选方案重叠最小的，重叠太多就跳过；实在凑不满再放宽。
    def _overlap(seq: tuple[POI, ...], chosen: list[set[str]]) -> float:
        ids = {p.id for p in seq}
        return max((len(ids & c) / len(ids | c) for c in chosen), default=0.0)

    selected: list[tuple[float, tuple[POI, ...], float, dict[str, float], list[float]]] = []
    chosen_sets: list[set[str]] = []

    for threshold in (0.2, 0.34, 1.01):
        for cand in candidates:
            if len(selected) >= top_k:
                break
            if cand in selected:
                continue
            if _overlap(cand[1], chosen_sets) < threshold:
                selected.append(cand)
                chosen_sets.append({p.id for p in cand[1]})
        if len(selected) >= top_k:
            break

    plans: list[Plan] = []
    for score, seq, total, per_member, offsets in selected[:top_k]:
        worst_member = min(per_member, key=lambda k: per_member[k])
        plans.append(
            Plan(
                items=list(seq),
                consensus=score,
                mean_score=sum(per_member.values()) / len(per_member),
                worst_score=per_member[worst_member],
                worst_member=worst_member,
                total_minutes=total,
                explanation=_explain(seq, per_member, prefs, total),
                per_member=per_member,
                offsets=offsets,
            )
        )
    return plans
