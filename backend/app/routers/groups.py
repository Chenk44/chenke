"""建局、入局、填偏好。"""

from __future__ import annotations

import random
import string

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from algo.loader import area_centroid, load_pois

from ..config import settings
from ..db import get_db
from ..models import Group, Member, PreferenceRecord
from ..schemas import (
    DemoOut,
    GroupCreate,
    GroupOut,
    MemberCreate,
    MemberOut,
    PreferenceIn,
    PreferenceOut,
)
from ..services.nlp import merge_hints, parse_constraints

router = APIRouter(prefix="/api", tags=["group"])

# 去掉 0/O/1/I 这些容易看错的字符，邀请码是要被人口头念出来的
CODE_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1I")


def _new_code(db: Session) -> str:
    for _ in range(20):
        code = "".join(random.choices(CODE_ALPHABET, k=6))
        exists = db.scalar(select(Group.id).where(Group.code == code))
        if not exists:
            return code
    raise HTTPException(status_code=500, detail="邀请码生成失败，请重试")


def get_group_or_404(code: str, db: Session) -> Group:
    group = db.scalar(select(Group).where(Group.code == code.upper()))
    if group is None:
        raise HTTPException(status_code=404, detail=f"找不到邀请码为 {code} 的局")
    return group


def group_to_out(group: Group) -> GroupOut:
    return GroupOut(
        id=group.id,
        code=group.code,
        name=group.name,
        city=group.city,
        meet_date=group.meet_date,
        budget=group.budget,
        origin_area=group.origin_area,
        weather=group.weather,
        window_minutes=group.window_minutes,
        created_at=group.created_at,
        members=[MemberOut.of(m, filled=m.preference is not None) for m in group.members],
    )


@router.post("/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
def create_group(payload: GroupCreate, db: Session = Depends(get_db)) -> GroupOut:
    """建一个局，返回 6 位邀请码。"""
    try:
        lat, lng = area_centroid(load_pois(), payload.origin_area)
    except KeyError:
        # 商圈不认识就用深圳中心兜底，不阻断建局
        lat, lng = 22.5431, 114.0579

    group = Group(
        code=_new_code(db),
        name=payload.name.strip(),
        origin_area=payload.origin_area,
        origin_lat=lat,
        origin_lng=lng,
        meet_date=payload.meet_date,
        budget=payload.budget,
        weather=(payload.weather or None),
        window_minutes=payload.window_minutes,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group_to_out(group)


@router.get("/groups/{code}", response_model=GroupOut)
def read_group(code: str, db: Session = Depends(get_db)) -> GroupOut:
    return group_to_out(get_group_or_404(code, db))


@router.post(
    "/groups/{code}/members",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
)
def join_group(code: str, payload: MemberCreate, db: Session = Depends(get_db)) -> MemberOut:
    """用邀请码 + 昵称入局。重名直接返回已有的那个人，避免刷新页面就多一个成员。"""
    group = get_group_or_404(code, db)
    nickname = payload.nickname.strip()
    if not nickname:
        raise HTTPException(status_code=400, detail="昵称不能为空")

    for m in group.members:
        if m.nickname == nickname:
            return MemberOut.of(m, filled=m.preference is not None)

    if len(group.members) >= settings.max_members:
        raise HTTPException(status_code=400, detail=f"这个局最多 {settings.max_members} 人")

    member = Member(group_id=group.id, nickname=nickname)
    db.add(member)
    db.commit()
    db.refresh(member)
    return MemberOut.of(member, filled=False)


def _get_member_or_404(member_id: int, db: Session) -> Member:
    member = db.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail="这个人不在任何局里")
    return member


def _pref_out(rec: PreferenceRecord | None, hints: list[str] | None = None) -> PreferenceOut:
    """记录 → 响应模型。没填过的人返回默认值，三处调用点共用一份。"""
    if rec is None:
        return PreferenceOut(parsed_hints=hints or [])
    return PreferenceOut(
        quiet=rec.quiet,
        price=rec.price,
        near=rec.near,
        max_price=rec.max_price,
        exclude_tags=list(rec.exclude_tags or []),
        indoor_pref=rec.indoor_pref,
        with_kids=rec.with_kids,
        has_car=rec.has_car,
        prefer_categories=list(rec.prefer_categories or []),
        exclude_categories=list(rec.exclude_categories or []),
        prefer_tags=list(rec.prefer_tags or []),
        max_minutes=rec.max_minutes,
        start_hour=rec.start_hour,
        free_text=rec.free_text,
        parsed_hints=hints or [],
    )


@router.put("/members/{member_id}/preference", response_model=PreferenceOut)
def save_preference(
    member_id: int, payload: PreferenceIn, db: Session = Depends(get_db)
) -> PreferenceOut:
    """填 / 改自己的偏好。auto_parse=true 时会把一句话解析成约束。"""
    member = _get_member_or_404(member_id, db)

    data = payload.model_dump()
    data.pop("auto_parse", None)
    hints: list[str] = []

    if payload.auto_parse and payload.free_text:
        parsed = parse_constraints(payload.free_text)
        merged = merge_hints(data, parsed)
        data = merged.values
        hints = merged.hints

    rec = member.preference
    if rec is None:
        rec = PreferenceRecord(member_id=member.id)
        db.add(rec)

    for key in (
        "quiet",
        "price",
        "near",
        "max_price",
        "exclude_tags",
        "indoor_pref",
        "with_kids",
        "has_car",
        "prefer_categories",
        "exclude_categories",
        "prefer_tags",
        "max_minutes",
        "start_hour",
        "free_text",
    ):
        setattr(rec, key, data.get(key))

    db.commit()
    db.refresh(rec)

    return _pref_out(rec, hints)


@router.get("/members/{member_id}/preference", response_model=PreferenceOut)
def read_preference(member_id: int, db: Session = Depends(get_db)) -> PreferenceOut:
    member = _get_member_or_404(member_id, db)
    return _pref_out(member.preference)


@router.post("/parse", response_model=PreferenceOut, tags=["nlp"])
def parse_text(payload: dict) -> PreferenceOut:
    """只解析不保存。前端可以在用户打字时调用，做实时提示。"""
    text = str(payload.get("text", ""))
    parsed = parse_constraints(text)
    return PreferenceOut(
        quiet=parsed.quiet if parsed.quiet is not None else 0.5,
        price=parsed.price if parsed.price is not None else 0.5,
        near=parsed.near if parsed.near is not None else 0.5,
        max_price=parsed.max_price,
        exclude_tags=list(parsed.exclude_tags),
        indoor_pref=parsed.indoor_pref or 0,
        with_kids=bool(parsed.with_kids),
        has_car=bool(parsed.has_car),
        prefer_categories=list(parsed.prefer_categories),
        exclude_categories=list(parsed.exclude_categories),
        prefer_tags=list(parsed.prefer_tags),
        max_minutes=parsed.max_minutes,
        start_hour=parsed.start_hour,
        free_text=text,
        parsed_hints=parsed.hints,
    )


# 示例局：五个口味互相冲突的人，正是产品要解决的场景
DEMO_MEMBERS: tuple[dict, ...] = (
    {
        "nickname": "小林",
        "quiet": 0.85,
        "price": 0.25,
        "near": 0.2,
        "free_text": "想安静点，下雨天别走太远，人均 100 以内",
    },
    {
        "nickname": "阿May",
        "quiet": 0.35,
        "price": 0.75,
        "near": 0.6,
        "free_text": "想热闹一点，可以跑远",
    },
    {
        "nickname": "老王",
        "quiet": 0.5,
        "price": 0.3,
        "near": 0.35,
        "with_kids": True,
        "free_text": "带娃，别吃辣",
    },
    {
        "nickname": "Cici",
        "quiet": 0.6,
        "price": 0.55,
        "near": 0.8,
        "exclude_tags": ["海鲜"],
        "free_text": "海鲜过敏",
    },
    {
        "nickname": "大熊",
        "quiet": 0.4,
        "price": 0.5,
        "near": 0.5,
        "has_car": True,
        "free_text": "我开车，可以带三个人",
    },
)


@router.post("/demo", response_model=DemoOut, status_code=status.HTTP_201_CREATED, tags=["demo"])
def create_demo(db: Session = Depends(get_db)) -> DemoOut:
    """一键生成一个填好的示例局。

    为什么要有这个接口：第一次打开应用的人（和评委）不该先花三分钟建局、
    再编五个人的口味才能看到效果。点一下，直接看到产品最终形态。
    """
    try:
        lat, lng = area_centroid(load_pois(), "海岸城")
    except KeyError:  # 数据表缺海岸城时退回深圳中心
        lat, lng = 22.5431, 114.0579

    group = Group(
        code=_new_code(db),
        name="示例：周六下午五个人",
        origin_area="海岸城",
        origin_lat=lat,
        origin_lng=lng,
        weather="rain",
        budget=150,
        window_minutes=360,
    )
    db.add(group)
    db.flush()

    first: Member | None = None
    for spec in DEMO_MEMBERS:
        member = Member(group_id=group.id, nickname=spec["nickname"])
        db.add(member)
        db.flush()
        first = first or member

        # 走一遍和真实用户相同的解析逻辑，示例里的一句话解析结果才是真的
        base = {
            "quiet": spec["quiet"],
            "price": spec["price"],
            "near": spec["near"],
            "max_price": None,
            "exclude_tags": list(spec.get("exclude_tags", [])),
            "indoor_pref": 0,
            "with_kids": spec.get("with_kids", False),
            "has_car": spec.get("has_car", False),
            "prefer_categories": [],
            "exclude_categories": [],
            "prefer_tags": [],
            "max_minutes": None,
            "start_hour": None,
            "free_text": spec["free_text"],
        }
        values = merge_hints(base, parse_constraints(spec["free_text"])).values
        db.add(PreferenceRecord(member_id=member.id, **values))

    db.commit()
    return DemoOut(
        code=group.code,
        member_id=first.id if first else 0,
        nickname=first.nickname if first else "",
        members=len(DEMO_MEMBERS),
    )
