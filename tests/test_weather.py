"""天气自动填充：选日期就知道那天什么天。

这里所有用例都 monkeypatch 掉 `forecast_map`，跑测试时不碰网络——
CI 机器没网也必须全绿，这正是「查不到天气照样能建局」的回归测试。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from app.services import weather as w


@pytest.fixture(autouse=True)
def _clean_cache():
    w.reset_cache()
    yield
    w.reset_cache()


def _forecast(day: date, text: str, high: float = 26.0, low: float = 21.0) -> w.Forecast:
    return w.Forecast(date=day, day_text=text, night_text=text, high=high, low=low, source="amap")


def test_weather_words_become_the_four_kinds_we_use():
    assert w.kind_of("中雨") == "rain"
    assert w.kind_of("多云", "暴雨") == "rain"  # 白天多云、晚上暴雨，这天照样算雨天
    assert w.kind_of("雷阵雨") == "storm"
    assert w.kind_of("台风") == "storm"
    assert w.kind_of("晴", "晴", 35) == "hot"
    assert w.kind_of("晴", "晴", 28) == "clear"


def test_open_meteo_codes_are_translated():
    assert w.WMO_TEXT[0] == "晴"
    assert w.WMO_TEXT[95] == "雷阵雨"
    # 代码走过来的天气也要能落进这四类，否则补的那几天等于没补
    assert w.kind_of(w.WMO_TEXT[65]) == "rain"
    assert w.kind_of(w.WMO_TEXT[99]) == "storm"


def test_window_is_seven_days_from_today():
    days = w.window()
    assert len(days) == w.MAX_DAYS == 7
    assert days[0] == date.today()
    assert days[-1] == date.today() + timedelta(days=6)


def test_forecast_carries_temperatures_for_display():
    item = _forecast(date.today(), "中雨")
    assert w.describe(item) == "中雨 26°/21°"
    bare = w.Forecast(date=date.today(), day_text="多云", night_text="")
    assert w.describe(bare) == "多云"  # 没有温度就只显示天气词


def test_out_of_range_date_is_explicitly_out_of_range(client, monkeypatch):
    monkeypatch.setattr(w, "forecast_map", lambda force=False: {})
    far = (date.today() + timedelta(days=30)).isoformat()
    body = client.get("/api/weather", params={"date": far}).json()
    assert body["in_range"] is False
    assert body["kind"] is None
    assert "7 天" in body["message"]


def test_api_returns_the_forecast(client, monkeypatch):
    tomorrow = date.today() + timedelta(days=1)
    monkeypatch.setattr(
        w, "forecast_map", lambda force=False: {tomorrow: _forecast(tomorrow, "中雨")}
    )
    body = client.get("/api/weather", params={"date": tomorrow.isoformat()}).json()
    assert body["in_range"] is True
    assert body["kind"] == "rain"
    assert body["text"] == "中雨"
    assert body["source"] == "amap"


def test_group_picks_up_the_weather_of_its_date(client, monkeypatch):
    day = date.today() + timedelta(days=2)
    monkeypatch.setattr(w, "forecast_map", lambda force=False: {day: _forecast(day, "雷阵雨")})
    resp = client.post(
        "/api/groups",
        json={"name": "周六去哪", "origin_area": "海岸城", "meet_date": day.isoformat()},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["weather"] == "storm"
    assert "雷阵雨" in body["weather_text"]


def test_manual_weather_beats_the_forecast(client, monkeypatch):
    day = date.today() + timedelta(days=2)
    monkeypatch.setattr(w, "forecast_map", lambda force=False: {day: _forecast(day, "晴")})
    body = client.post(
        "/api/groups",
        json={
            "name": "周六去哪",
            "origin_area": "海岸城",
            "meet_date": day.isoformat(),
            "weather": "rain",
        },
    ).json()
    assert body["weather"] == "rain"


def test_no_forecast_still_creates_the_group(client, monkeypatch):
    """断网 / 日期太远时，建局不能失败——只是没有天气这项。"""
    monkeypatch.setattr(w, "forecast_map", lambda force=False: {})
    resp = client.post(
        "/api/groups",
        json={
            "name": "周六去哪",
            "origin_area": "海岸城",
            "meet_date": (date.today() + timedelta(days=2)).isoformat(),
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["weather"] is None
    assert body["weather_text"] is None
