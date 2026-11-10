"""推荐流水线：把偏好、地点池、天气、出发点编排成一次完整调用。

调用顺序：
    偏好 → 天气修正 → 单人打分矩阵 → 群体聚合 → 组合搜索 → 方案

任何一步都可以单独测试，这是把算法放在独立包（而不是塞进路由）的原因。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .aggregate import Consensus, aggregate, rank_agreement
from .combine import build_plans
from .geo import estimate_travel_minutes
from .types import POI, Plan, Preference
from .utility import score_poi

RAINY = {"rain", "storm", "thunder", "雨", "暴雨", "台风"}
HOT = {"hot", "高温"}


@dataclass
class Recommendation:
    """一次推荐的完整结果，包含方案和解释所需的中间数据。"""

    plans: list[Plan]
    top_pois: list[Consensus]
    agreement: float                       # 两种聚合规则的一致度 0~1
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "plans": [
                {
                    "items": [
                        {
                            "id": p.id,
                            "name": p.name,
                            "area": p.area,
                            "category": p.category,
                            "avg_price": p.avg_price,
                            "blurb": p.blurb,
                            "offset_minutes": round(plan.offsets[i] if i < len(plan.offsets) else 0.0, 1),
                        }
                        for i, p in enumerate(plan.items)
                    ],
                    "consensus": round(plan.consensus, 4),
                    "mean_score": round(plan.mean_score, 4),
                    "worst_score": round(plan.worst_score, 4),
                    "worst_member": plan.worst_member,
                    "total_minutes": round(plan.total_minutes, 1),
                    "explanation": plan.explanation,
                    "per_member": {k: round(v, 4) for k, v in plan.per_member.items()},
                }
                for plan in self.plans
            ],
            "top_pois": [
                {
                    "id": c.poi_id,
                    "consensus": round(c.consensus, 4),
                    "mean": round(c.mean, 4),
                    "worst": round(c.worst, 4),
                    "worst_member": c.worst_member,
                    "borda": round(c.borda, 4),
                    "regret": round(c.regret, 4),
                    "spread": round(c.spread, 4),
                }
                for c in self.top_pois[:10]
            ],
            "agreement": round(self.agreement, 4),
            "notes": self.notes,
        }


def apply_weather(prefs: list[Preference], weather: str | None) -> list[str]:
    """按天气修正偏好，返回给用户看的提示。"""
    notes: list[str] = []
    if not weather:
        return notes
    w = weather.strip().lower()
    if w in RAINY:
        for p in prefs:
            p.require_indoor = True
        notes.append("💧 检测到降雨，已自动优先室内地点")
    elif w in HOT:
        for p in prefs:
            p.require_indoor = True
        notes.append("🥵 高温天气，已优先有空调的室内地点")
    return notes


def recommend(
    pois: list[POI],
    prefs: list[Preference],
    origin: tuple[float, float],
    group_size: int | None = None,
    weather: str | None = None,
    window_minutes: float = 360.0,
    top_k: int = 3,
    meet_date: date | None = None,
) -> Recommendation:
    """主入口。origin 是出发点坐标（一般是集合地点）。"""
    if not pois:
        raise ValueError("地点池为空，请先执行 python -m scripts.seed")
    if not prefs:
        raise ValueError("还没有人填写偏好")

    notes = apply_weather(prefs, weather)
    size = group_size or len(prefs)

    # 1) 单人 × 单地点 打分矩阵
    matrix: dict[str, dict[str, float]] = {}
    for pref in prefs:
        row: dict[str, float] = {}
        for poi in pois:
            minutes = estimate_travel_minutes(
                origin[0], origin[1], poi.lat, poi.lng, has_car=pref.has_car
            )
            row[poi.id] = score_poi(poi, pref, minutes, group_size=size).score
        matrix[pref.member_id] = row

    # 2) 群体聚合
    ranked = aggregate(matrix)
    consensus = {c.poi_id: c for c in ranked}
    agreement = rank_agreement(matrix)

    # 3) 组合搜索
    plans = build_plans(
        pois=pois,
        prefs=prefs,
        matrix=matrix,
        consensus=consensus,
        origin=origin,
        group_size=size,
        window_minutes=window_minutes,
        top_k=top_k,
    )

    if len(plans) == 0:
        notes.append("⚠️ 偏好冲突太强，没有找到能凑成动线的组合，建议放宽预算或人数")
    elif plans[0].worst_score < 0.35:
        notes.append(f"⚠️ 方案对 {plans[0].worst_member} 不太友好，可以让他少填一点硬约束")

    if agreement < 0.6:
        notes.append("ℹ️ 两种聚合规则排序差异较大，说明这组偏好分歧明显，建议投票定案")

    return Recommendation(plans=plans, top_pois=ranked, agreement=agreement, notes=notes)
