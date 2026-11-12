"""查某一天的天气。

建局时选定日期 → 前端问这个接口 → 那天下不下雨就自动填进偏好，
不用退出去别的 App 看一眼再回来手选。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from ..schemas import WeatherOut
from ..services import weather as weather_service

router = APIRouter(prefix="/api", tags=["weather"])


@router.get("/weather", response_model=WeatherOut)
def read_weather(day: date = Query(alias="date", description="哪一天，YYYY-MM-DD")) -> WeatherOut:
    """能自动查到就给具体天气，查不到就明说查不到，别让前端猜。"""
    available = weather_service.available_dates()

    if day not in weather_service.window():
        return WeatherOut(
            date=day,
            in_range=False,
            message="只能预知 7 天内的天气，换个近点的日子，或者手动选天气",
            available_dates=available,
        )

    item = weather_service.forecast_for(day)
    if item is None:
        return WeatherOut(
            date=day,
            in_range=True,
            message="这天的预报暂时没查到（天气接口不通），可以先手动选",
            available_dates=available,
        )

    return WeatherOut(
        date=day,
        in_range=True,
        kind=item.kind,
        text=item.text,
        high=item.high,
        low=item.low,
        precip=item.precip,
        source=item.source,
        available_dates=available,
    )
