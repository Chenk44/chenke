"""众口 · 推荐算法包。

对外只暴露少量接口，Web 层不直接碰内部实现：

    from algo import load_pois, recommend
"""

from __future__ import annotations

from .aggregate import Consensus, aggregate, rank_agreement
from .combine import build_plans
from .loader import load_pois
from .pipeline import Recommendation, recommend
from .types import CATEGORIES, POI, Plan, Preference

__all__ = [
    "CATEGORIES",
    "POI",
    "Plan",
    "Preference",
    "Consensus",
    "Recommendation",
    "aggregate",
    "build_plans",
    "load_pois",
    "rank_agreement",
    "recommend",
]
