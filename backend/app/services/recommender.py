"""把数据库里的行翻译成算法包认识的对象，再调用算法。

这一层是唯一知道「数据库怎么存」和「算法怎么想」两边细节的地方，
换成别的存储或别的算法时，只需要改这里。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from algo import POI, Preference, Recommendation, recommend
from algo.loader import load_pois

from ..models import Group, Member, POIRecord


class RecommendError(RuntimeError):
    """推荐前置条件不满足，会被路由层翻译成 400。"""


def record_to_poi(rec: POIRecord) -> POI:
    return POI(
        id=rec.id,
        name=rec.name,
        area=rec.area,
        district=rec.district,
        category=rec.category,
        lat=rec.lat,
        lng=rec.lng,
        avg_price=rec.avg_price,
        rating=rec.rating,
        indoor=rec.indoor,
        quiet=rec.quiet,
        min_people=rec.min_people,
        max_people=rec.max_people,
        kid_friendly=rec.kid_friendly,
        need_booking=rec.need_booking,
        queue=rec.queue,
        tags=tuple(t for t in (rec.tags or "").split("|") if t),
        blurb=rec.blurb,
    )


def get_pois(db: Session) -> list[POI]:
    """优先读数据库；数据库空则退回读 CSV，保证第一次跑就能用。"""
    rows = db.scalars(select(POIRecord)).all()
    if rows:
        return [record_to_poi(r) for r in rows]
    return load_pois()


def member_to_preference(member: Member, group: Group) -> Preference:
    p = member.preference
    if p is None:
        # 没填的人按中立处理，至少不会因为「空白」被算法忽略
        return Preference(member_id=member.nickname or str(member.id))

    max_price = p.max_price
    if group.budget is not None:
        max_price = group.budget if max_price is None else min(max_price, group.budget)

    return Preference(
        member_id=member.nickname or str(member.id),
        quiet=p.quiet,
        price=p.price,
        near=p.near,
        max_price=max_price,
        exclude_tags=tuple(p.exclude_tags or ()),
        indoor_pref=p.indoor_pref,
        with_kids=p.with_kids,
        has_car=p.has_car,
        free_text=p.free_text,
    )


def run_recommendation(db: Session, group: Group) -> Recommendation:
    """对一个局跑一次完整推荐。"""
    members = [m for m in group.members if m.nickname]
    if len(members) < 1:
        raise RecommendError("还没有人加入这个局")
    filled = [m for m in members if m.preference is not None]
    if not filled:
        raise RecommendError("还没有人填写偏好，先让至少一个人填一下")

    prefs = [member_to_preference(m, group) for m in filled]
    pois = get_pois(db)
    if not pois:
        raise RecommendError("地点库是空的，请先运行 python -m scripts.seed")

    return recommend(
        pois=pois,
        prefs=prefs,
        origin=(group.origin_lat, group.origin_lng),
        group_size=len(members),
        weather=group.weather,
        window_minutes=group.window_minutes,
        top_k=3,
    )


def nickname_map(group: Group) -> dict[str, str]:
    """算法里用 member_id 字符串做 key，展示时要换回昵称。"""
    return {str(m.id): m.nickname for m in group.members}
