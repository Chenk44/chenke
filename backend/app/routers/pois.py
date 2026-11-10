"""地点库和事后评价。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from algo.loader import areas

from ..db import get_db
from ..models import POIRecord, Review
from ..schemas import POIOut, ReviewIn, ReviewOut
from ..services.recommender import get_pois

router = APIRouter(prefix="/api", tags=["poi"])


@router.get("/pois", response_model=list[POIOut])
def list_pois(
    area: str | None = Query(default=None, description="按商圈过滤，例如 海岸城"),
    category: str | None = Query(default=None, description="按品类过滤，例如 餐饮"),
    indoor: bool | None = Query(default=None, description="只看室内"),
    db: Session = Depends(get_db),
) -> list[POIOut]:
    stmt = select(POIRecord)
    if area:
        stmt = stmt.where(POIRecord.area == area)
    if category:
        stmt = stmt.where(POIRecord.category == category)
    if indoor is not None:
        stmt = stmt.where(POIRecord.indoor == indoor)

    rows = db.scalars(stmt.order_by(POIRecord.area, POIRecord.rating.desc())).all()
    return [
        POIOut(
            id=r.id,
            name=r.name,
            area=r.area,
            district=r.district,
            category=r.category,
            avg_price=r.avg_price,
            rating=r.rating,
            indoor=r.indoor,
            kid_friendly=r.kid_friendly,
            tags=[t for t in (r.tags or "").split("|") if t],
            blurb=r.blurb,
        )
        for r in rows
    ]


@router.get("/areas", response_model=list[str])
def list_areas(db: Session = Depends(get_db)) -> list[str]:
    """给前端下拉框用的商圈列表。"""
    return areas(get_pois(db))


@router.post("/reviews", response_model=ReviewOut)
def add_review(payload: ReviewIn, db: Session = Depends(get_db)) -> ReviewOut:
    """玩完之后打分。同一个地点同一个人只保留最后一次。"""
    poi = db.get(POIRecord, payload.poi_id)
    if poi is None:
        raise HTTPException(status_code=404, detail="地点不存在")

    existing = db.scalar(
        select(Review).where(
            Review.poi_id == payload.poi_id, Review.member_id == payload.member_id
        )
    )
    if existing is None:
        existing = Review(poi_id=payload.poi_id, member_id=payload.member_id)
        db.add(existing)

    existing.rating = payload.rating
    existing.comment = payload.comment
    db.commit()
    db.refresh(existing)
    return ReviewOut.model_validate(existing)


@router.get("/pois/{poi_id}/reviews", response_model=list[ReviewOut])
def list_reviews(poi_id: str, db: Session = Depends(get_db)) -> list[ReviewOut]:
    rows = db.scalars(select(Review).where(Review.poi_id == poi_id)).all()
    return [ReviewOut.model_validate(r) for r in rows]
