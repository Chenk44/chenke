"""请求 / 响应模型。

FastAPI 会自动把它们变成 OpenAPI 文档（/docs），
这是选 Python 最实际的收益之一：接口文档不用手写，也不会和实现脱节。
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

# ---------- 建局 ----------


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60, description="这个局叫什么，例如「周六去哪」")
    origin_area: str = Field(default="海岸城", description="集合商圈，决定默认出发点")
    meet_date: date | None = Field(default=None, description="哪一天")
    budget: float | None = Field(default=None, ge=0, le=5000, description="人均预算上限")
    weather: str | None = Field(default=None, description="rain / hot / clear，留空则不修正")
    window_minutes: int = Field(default=360, ge=120, le=720, description="可玩多久")


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nickname: str
    filled: bool = Field(default=False, description="是否已填偏好")

    @classmethod
    def of(cls, member, filled: bool) -> MemberOut:
        return cls(id=member.id, nickname=member.nickname, filled=filled)


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    city: str
    meet_date: date | None
    budget: float | None
    origin_area: str
    weather: str | None
    weather_text: str | None = None
    window_minutes: int
    created_at: datetime
    members: list[MemberOut] = []


class WeatherOut(BaseModel):
    """某一天的天气：能自动查到就带具体数字，查不到就只回 in_range=false。"""

    date: date
    in_range: bool
    kind: str | None = Field(default=None, description="storm / rain / hot / clear")
    text: str | None = None
    high: float | None = None
    low: float | None = None
    precip: int | None = None
    source: str | None = None
    message: str = ""
    available_dates: list[str] = []


# ---------- 入局 / 填偏好 ----------


class MemberCreate(BaseModel):
    nickname: str = Field(min_length=1, max_length=30)


class DemoOut(BaseModel):
    """示例局：给第一次打开的人一个「已经填好」的局，直接看结果。"""

    code: str
    member_id: int
    nickname: str
    members: int


class PreferenceIn(BaseModel):
    quiet: float = Field(default=0.5, ge=0, le=1, description="0 热闹 ~ 1 安静")
    price: float = Field(default=0.5, ge=0, le=1, description="0 省钱 ~ 1 舍得")
    near: float = Field(default=0.5, ge=0, le=1, description="0 想近 ~ 1 愿意跑远")
    max_price: float | None = Field(default=None, ge=0, le=5000)
    exclude_tags: list[str] = Field(default_factory=list, description="忌口，例如 ['辣']")
    indoor_pref: int = Field(
        default=0, ge=-1, le=1, description="-1 想出去 / 0 无所谓 / +1 想待室内"
    )
    with_kids: bool = False
    has_car: bool = False
    prefer_categories: list[str] = Field(
        default_factory=list, description="想去的品类，例如 ['餐饮']"
    )
    exclude_categories: list[str] = Field(default_factory=list, description="不想去的品类")
    prefer_tags: list[str] = Field(default_factory=list, description="想要的体验标签")
    max_minutes: int | None = Field(default=None, ge=60, le=720, description="最多玩多久")
    start_hour: int | None = Field(default=None, ge=6, le=23, description="打算几点出发")
    free_text: str = Field(default="", max_length=200, description="一句话，例如「下雨天别走太远」")
    auto_parse: bool = Field(default=True, description="是否用规则把一句话解析成约束")


class PreferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    quiet: float
    price: float
    near: float
    max_price: float | None
    exclude_tags: list[str]
    indoor_pref: int
    with_kids: bool
    has_car: bool
    prefer_categories: list[str] = []
    exclude_categories: list[str] = []
    prefer_tags: list[str] = []
    max_minutes: int | None = None
    start_hour: int | None = None
    free_text: str
    parsed_hints: list[str] = Field(default_factory=list, description="从一句话里解读到的约束")


# ---------- 推荐结果 ----------


class PlanItemOut(BaseModel):
    id: str
    name: str
    area: str
    category: str
    avg_price: float
    blurb: str
    indoor: bool = True
    offset_minutes: float = Field(default=0.0, description="从出发算起第几分钟到，用于渲染时间线")
    hours: str = Field(default="", description="营业时间，例如 10:00-22:00；空串表示全天")
    closed: bool = Field(default=False, description="按时间线算，到这个点时已经打烊")


class PlanOut(BaseModel):
    id: int = Field(description="投票时要用这个 id")
    start_minute: int = Field(default=840, description="出发时刻，从 0 点算起")
    items: list[PlanItemOut]
    consensus: float
    mean_score: float
    worst_score: float
    worst_member: str
    total_minutes: float
    day_cost: float = Field(default=0.0, description="这一天人均花多少（各站相加）")
    day_budget: float | None = Field(default=None, description="局的日预算；None 表示没设")
    explanation: str
    per_member: dict[str, float]


class ConsensusOut(BaseModel):
    id: str
    consensus: float
    mean: float
    worst: float
    worst_member: str
    borda: float
    regret: float
    spread: float


class RecommendOut(BaseModel):
    plans: list[PlanOut]
    top_pois: list[ConsensusOut]
    agreement: float
    notes: list[str]


# ---------- 投票 ----------


class VoteIn(BaseModel):
    member_id: int


class VoteOut(BaseModel):
    plan_id: int
    votes: int
    voters: list[str]
    winner: bool = False


# ---------- 地点 / 评价 ----------


class POIOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    area: str
    district: str
    category: str
    avg_price: float
    rating: float
    indoor: bool
    kid_friendly: bool
    tags: list[str]
    blurb: str
    open_hour: float = 0.0
    close_hour: float = 24.0


class ReviewIn(BaseModel):
    member_id: int
    poi_id: str
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=500)


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    poi_id: str
    member_id: int
    rating: int
    comment: str
