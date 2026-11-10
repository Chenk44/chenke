"""核心数据模型：一个地点（POI）和一个人的偏好（Preference）。

这两个结构是整个推荐算法的输入契约，刻意做成纯 dataclass，
不依赖数据库、不依赖 Web 框架，方便单独测试和复用。
"""

from __future__ import annotations

from dataclasses import dataclass, field


# 允许的地点品类。组合方案时用「品类不重复」来保证体验多样（咖啡 + 展览 + 吃饭）。
CATEGORIES = (
    "餐饮",   # 正餐
    "咖啡",   # 咖啡 / 茶饮 / 甜品
    "展览",   # 美术馆 / 展馆 / 书店
    "公园",   # 公园 / 海滨 / 爬山
    "影院",   # 电影院
    "夜生活", # bar / 夜市 / 演出
    "玩乐",   # 桌游 / 密室 / 电玩 / 摩天轮
)


@dataclass(frozen=True)
class POI:
    """一个候选地点。字段全部来自 `data/pois_shenzhen.csv`，由人工维护。"""

    id: str
    name: str
    area: str            # 商圈，例如「海岸城」
    district: str        # 行政区，例如「南山区」
    category: str        # 见 CATEGORIES
    lat: float
    lng: float
    avg_price: float     # 人均消费（元）
    rating: float        # 0.0 ~ 5.0
    indoor: bool         # 是否室内（下雨天权重）
    quiet: float         # 0.0 很热闹 ~ 1.0 很安静
    min_people: int      # 适合的最小人数
    max_people: int      # 适合的最大人数
    kid_friendly: bool
    need_booking: bool
    queue: float         # 0.0 不排队 ~ 1.0 排很久
    tags: tuple[str, ...] = ()   # 自由标签，用于忌口/偏好惩罚
    blurb: str = ""              # 一句话推荐理由，直接展示给用户

    def has_any_tag(self, tags: set[str] | frozenset[str]) -> bool:
        return bool(set(self.tags) & set(tags))


@dataclass
class Preference:
    """一个人的偏好。前三个是滑杆（0~1），其余是硬约束或开关。"""

    member_id: str
    quiet: float = 0.5        # 0 热闹 ~ 1 安静
    price: float = 0.5        # 0 省钱 ~ 1 舍得花
    near: float = 0.5         # 0 越近越好 ~ 1 愿意跑远
    max_price: float | None = None   # 硬性预算上限（人均），None 表示不限
    exclude_tags: tuple[str, ...] = ()   # 忌口/排斥标签，例如 ("辣", "海鲜")
    require_indoor: bool = False     # 例如带婴儿、下雨
    with_kids: bool = False
    has_car: bool = False
    free_text: str = ""              # 用户原话，保留用于展示和 LLM 解析

    def hard_tags(self) -> frozenset[str]:
        return frozenset(self.exclude_tags)


@dataclass
class ScoredPOI:
    """单个地点对单个人的打分结果，保留各分项便于解释。"""

    poi: POI
    score: float                     # 0~1
    travel_minutes: float = 0.0
    parts: dict[str, float] = field(default_factory=dict)

    def why(self) -> str:
        """把分项拆解成一句人话，用于「为什么推荐这里」。"""
        if not self.parts:
            return ""
        ordered = sorted(self.parts.items(), key=lambda kv: kv[1], reverse=True)
        best = "、".join(f"{k}{v:+.2f}" for k, v in ordered[:2])
        worst = "、".join(f"{k}{v:+.2f}" for k, v in ordered[-1:])
        return f"加分项：{best}；扣分项：{worst}"


@dataclass
class Plan:
    """一个候选方案：2~3 个地点按顺序连成的一条动线。"""

    items: list[POI]
    consensus: float                 # 共识分 0~1，越高代表「大家都能接受」
    mean_score: float                # 平均满意度
    worst_score: float               # 最不满意那个人的满意度（公平性）
    worst_member: str                # 最不满意的人
    total_minutes: float             # 方案总耗时（含路程）
    explanation: str                 # 一句话解释
    per_member: dict[str, float] = field(default_factory=dict)
    # 每个地点「从出发算起第几分钟到达」，用于渲染 14:00 / 15:30 这样的时间线
    offsets: list[float] = field(default_factory=list)
