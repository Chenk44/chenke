"""ORM 模型。

设计说明（答辩会被问到的点）：
- 成员不绑定账号。一个局用 6 位邀请码加入，昵称即身份，
  因为「朋友群里说服大家注册」是这个产品最大的流失点。
- 偏好单独一张表，和成员一对一，方便「还没填」这个状态存在。
- 推荐结果整份存成 JSON（plans.payload）。方案是一次计算的快照，
  不应该在别人投票后悄悄变化，所以不做关系化拆表。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Group(Base):
    """一次「攒局」。"""

    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(60))
    city: Mapped[str] = mapped_column(String(30), default="深圳")
    meet_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    budget: Mapped[float | None] = mapped_column(Float, nullable=True)  # 人均预算上限
    origin_area: Mapped[str] = mapped_column(String(30), default="海岸城")
    origin_lat: Mapped[float] = mapped_column(Float, default=22.518)
    origin_lng: Mapped[float] = mapped_column(Float, default=113.936)
    weather: Mapped[str | None] = mapped_column(String(20), nullable=True)
    window_minutes: Mapped[int] = mapped_column(Integer, default=360)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    members: Mapped[list[Member]] = relationship(
        back_populates="group", cascade="all, delete-orphan", lazy="selectin"
    )
    plans: Mapped[list[PlanRecord]] = relationship(
        back_populates="group", cascade="all, delete-orphan", lazy="selectin"
    )


class Member(Base):
    """参与者。昵称即身份，不设密码。"""

    __tablename__ = "members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    nickname: Mapped[str] = mapped_column(String(30))
    joined_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    group: Mapped[Group] = relationship(back_populates="members")
    preference: Mapped[PreferenceRecord | None] = relationship(
        back_populates="member", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )


class PreferenceRecord(Base):
    """一个人的偏好。三个滑杆 + 硬约束。"""

    __tablename__ = "preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(
        ForeignKey("members.id", ondelete="CASCADE"), unique=True, index=True
    )
    quiet: Mapped[float] = mapped_column(Float, default=0.5)
    price: Mapped[float] = mapped_column(Float, default=0.5)
    near: Mapped[float] = mapped_column(Float, default=0.5)
    max_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exclude_tags: Mapped[list] = mapped_column(JSON, default=list)  # ["辣", "海鲜"]
    # -1 想出去 / 0 无所谓 / +1 想待室内，三态语义见 algo/types.py 的 Preference
    indoor_pref: Mapped[int] = mapped_column(Integer, default=0)
    with_kids: Mapped[bool] = mapped_column(Boolean, default=False)
    has_car: Mapped[bool] = mapped_column(Boolean, default=False)
    # 一句话解析出来的软约束，字段含义见 algo/types.py 的 Preference
    prefer_categories: Mapped[list] = mapped_column(JSON, default=list)  # ["餐饮"]
    exclude_categories: Mapped[list] = mapped_column(JSON, default=list)  # ["玩乐"]
    prefer_tags: Mapped[list] = mapped_column(JSON, default=list)  # ["拍照"]
    max_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 180
    start_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 19
    free_text: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    member: Mapped[Member] = relationship(back_populates="preference")


class POIRecord(Base):
    """地点。由 `python -m scripts.seed` 从 data/pois_shenzhen.csv 灌入。"""

    __tablename__ = "pois"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    area: Mapped[str] = mapped_column(String(30), index=True)
    district: Mapped[str] = mapped_column(String(30), index=True)
    category: Mapped[str] = mapped_column(String(20), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    avg_price: Mapped[float] = mapped_column(Float, default=0)
    rating: Mapped[float] = mapped_column(Float, default=0)
    indoor: Mapped[bool] = mapped_column(Boolean, default=False)
    quiet: Mapped[float] = mapped_column(Float, default=0.5)
    min_people: Mapped[int] = mapped_column(Integer, default=1)
    max_people: Mapped[int] = mapped_column(Integer, default=10)
    kid_friendly: Mapped[bool] = mapped_column(Boolean, default=False)
    need_booking: Mapped[bool] = mapped_column(Boolean, default=False)
    queue: Mapped[float] = mapped_column(Float, default=0)
    tags: Mapped[str] = mapped_column(String(200), default="")
    blurb: Mapped[str] = mapped_column(String(200), default="")
    # 营业时间（24 小时制，> 24 表示跨零点）；默认全天，老库补列后就是 0/24
    open_hour: Mapped[float] = mapped_column(Float, default=0.0)
    close_hour: Mapped[float] = mapped_column(Float, default=24.0)


class PlanRecord(Base):
    """一次推荐产出的方案快照。"""

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    rank: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    group: Mapped[Group] = relationship(back_populates="plans")
    votes: Mapped[list[Vote]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", lazy="selectin"
    )


class Vote(Base):
    """投票。一人在一个方案上只能投一次。"""

    __tablename__ = "votes"
    __table_args__ = (UniqueConstraint("plan_id", "member_id", name="uq_vote_plan_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    plan: Mapped[PlanRecord] = relationship(back_populates="votes")


class Review(Base):
    """玩完之后的真实评价。这是「朋友的口味比陌生人更可信」的数据来源。"""

    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("poi_id", "member_id", name="uq_review_poi_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    poi_id: Mapped[str] = mapped_column(String(40), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    rating: Mapped[int] = mapped_column(Integer, default=5)  # 1~5
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
