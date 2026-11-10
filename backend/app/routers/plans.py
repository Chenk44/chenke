"""出方案、投票定案。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Group, PlanRecord, Vote
from ..schemas import PlanItemOut, PlanOut, RecommendOut, VoteIn, VoteOut
from ..services.recommender import RecommendError, run_recommendation
from .groups import get_group_or_404

router = APIRouter(prefix="/api", tags=["plan"])


def _nickify(payload: dict, group: Group) -> dict:
    """把 payload 里的人换成昵称，前端直接显示。

    算法现在直接用昵称做 key；这里保留 id → 昵称的映射，是为了让
    早期用 member_id 存下来的方案快照（存在数据库里的 JSON）仍然能正确显示。
    """
    by_id = {str(m.id): m.nickname for m in group.members}
    known = {m.nickname for m in group.members}

    def name_of(value) -> str:
        text = str(value)
        return text if text in known else by_id.get(text, text)

    out = dict(payload)
    out["worst_member"] = name_of(payload.get("worst_member") or "有人")
    out["per_member"] = {name_of(k): v for k, v in (payload.get("per_member") or {}).items()}
    return out


def plan_to_out(record: PlanRecord, group: Group) -> PlanOut:
    p = _nickify(record.payload, group)
    return PlanOut(
        id=record.id,
        items=[PlanItemOut(**item) for item in p["items"]],
        consensus=p["consensus"],
        mean_score=p["mean_score"],
        worst_score=p["worst_score"],
        worst_member=p["worst_member"],
        total_minutes=p["total_minutes"],
        explanation=p["explanation"],
        per_member=p["per_member"],
    )


@router.post("/groups/{code}/recommend", response_model=RecommendOut)
def make_recommendation(code: str, db: Session = Depends(get_db)) -> RecommendOut:
    """跑一次推荐。会覆盖上一次的结果——因为方案是基于当前偏好算的。"""
    group = get_group_or_404(code, db)

    try:
        result = run_recommendation(db, group)
    except RecommendError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 覆盖旧方案（连带旧投票，避免票数对不上新方案）
    db.execute(delete(PlanRecord).where(PlanRecord.group_id == group.id))
    db.flush()

    data = result.to_dict()
    for idx, plan in enumerate(data["plans"], start=1):
        db.add(PlanRecord(group_id=group.id, rank=idx, payload=plan))
    db.commit()

    records = db.scalars(
        select(PlanRecord).where(PlanRecord.group_id == group.id).order_by(PlanRecord.rank)
    ).all()

    return RecommendOut(
        plans=[plan_to_out(r, group) for r in records],
        top_pois=data["top_pois"],
        agreement=data["agreement"],
        notes=data["notes"],
    )


@router.get("/groups/{code}/plans", response_model=RecommendOut)
def list_plans(code: str, db: Session = Depends(get_db)) -> RecommendOut:
    group = get_group_or_404(code, db)
    records = db.scalars(
        select(PlanRecord).where(PlanRecord.group_id == group.id).order_by(PlanRecord.rank)
    ).all()
    if not records:
        raise HTTPException(status_code=404, detail="还没有生成方案，先调用 recommend")

    return RecommendOut(
        plans=[plan_to_out(r, group) for r in records],
        top_pois=[],
        agreement=0.0,
        notes=["这是上次生成的方案快照，偏好改动后请重新推荐"],
    )


@router.post("/plans/{plan_id}/vote", response_model=VoteOut)
def vote(plan_id: int, payload: VoteIn, db: Session = Depends(get_db)) -> VoteOut:
    """投票。同一个人重复投同一个方案不报错，只是幂等。"""
    record = db.get(PlanRecord, plan_id)
    if record is None:
        raise HTTPException(status_code=404, detail="方案不存在")

    existing = db.scalar(
        select(Vote).where(Vote.plan_id == plan_id, Vote.member_id == payload.member_id)
    )
    if existing is None:
        db.add(Vote(plan_id=plan_id, member_id=payload.member_id))
        db.commit()

    votes = db.scalars(select(Vote).where(Vote.plan_id == plan_id)).all()
    names = {m.id: m.nickname for m in record.group.members}
    return VoteOut(
        plan_id=plan_id,
        votes=len(votes),
        voters=[names.get(v.member_id, str(v.member_id)) for v in votes],
    )


@router.get("/groups/{code}/votes", response_model=list[VoteOut])
def tally(code: str, db: Session = Depends(get_db)) -> list[VoteOut]:
    """票数统计。票数相同的方案都标记为 winner，交给人工拍板。"""
    group = get_group_or_404(code, db)
    records = db.scalars(
        select(PlanRecord).where(PlanRecord.group_id == group.id).order_by(PlanRecord.rank)
    ).all()
    if not records:
        return []

    names = {m.id: m.nickname for m in group.members}
    counts = []
    for r in records:
        votes = db.scalars(select(Vote).where(Vote.plan_id == r.id)).all()
        counts.append((r.id, votes))

    peak = max((len(v) for _, v in counts), default=0)
    return [
        VoteOut(
            plan_id=pid,
            votes=len(votes),
            voters=[names.get(v.member_id, str(v.member_id)) for v in votes],
            winner=peak > 0 and len(votes) == peak,
        )
        for pid, votes in counts
    ]
