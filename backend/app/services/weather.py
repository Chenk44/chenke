"""选个日期，自动知道那天会不会下雨。

两级数据源，按「够不够用」排序而不是按「先来后到」：

1. **高德 weatherInfo**（`extensions=all`）：给今天 + 未来 3 天，中文天气词（`中雨`/`多云`），
   和 POI 数据同源，所以优先用它；
2. **Open-Meteo**：给 7~16 天，WMO 天气代码 + 降水概率，不要 key，用来补高德覆盖不到的那几天。

两者都挂只影响「天数够不够」，不影响建局：接口返回 `in_range=false`，
前端退回手动选天气。**演示当天如果断网，功能退化成手选，而不是报错。**
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import httpx

from ..config import settings

CITY_CODE = "440300"  # 深圳
SHENZHEN = (22.5431, 114.0579)
MAX_DAYS = 7
TIMEOUT = 6.0
CACHE_TTL = 1800.0  # 半小时内不重复打接口

# 高德的天气词 → 我们算法认识的四种天
STORM_WORDS = ("台风", "雷暴", "雷阵雨")
RAIN_WORDS = ("雨",)
HOT_THRESHOLD = 33.0

# WMO 天气代码 → 中文（只列中国南方会遇到的）
WMO_TEXT: dict[int, str] = {
    0: "晴",
    1: "晴间多云",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "毛毛雨",
    53: "毛毛雨",
    55: "毛毛雨",
    56: "冻雨",
    57: "冻雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "阵雨",
    81: "强阵雨",
    82: "暴雨",
    85: "阵雪",
    86: "强阵雪",
    95: "雷阵雨",
    96: "雷暴伴冰雹",
    99: "强雷暴",
}


@dataclass(frozen=True)
class Forecast:
    date: date
    day_text: str
    night_text: str
    high: float | None = None
    low: float | None = None
    precip: int | None = None
    source: str = "amap"

    @property
    def kind(self) -> str:
        """算法认识的天气类型：storm / rain / hot / clear。"""
        return kind_of(self.day_text, self.night_text, self.high)

    @property
    def text(self) -> str:
        """给人看的天气词：白天和晚上不一样时说「多云转小雨」，别只说白天。"""
        day = self.day_text or ""
        night = self.night_text or ""
        if day and night and day != night:
            return f"{day}转{night}"
        return day or night or "未知"


_cache: tuple[float, dict[date, Forecast]] = (0.0, {})


def describe(item: Forecast) -> str:
    """给用户看的一句话：「中雨 26°/21°」。"""
    if item.high is None or item.low is None:
        return item.text
    return f"{item.text} {item.high:.0f}°/{item.low:.0f}°"


def kind_of(day_text: str, night_text: str = "", high: float | None = None) -> str:
    """把天气词翻成 storm / rain / hot / clear。

    白天和晚上取「更糟」的那个：白天多云、晚上暴雨，这一天照样算雨天。
    """
    text = f"{day_text or ''} {night_text or ''}"
    if any(word in text for word in STORM_WORDS):
        return "storm"
    if any(word in text for word in RAIN_WORDS):
        return "rain"
    if high is not None and high >= HOT_THRESHOLD:
        return "hot"
    return "clear"


def _get(url: str, params: dict[str, object]) -> dict[str, object]:
    """先直连，失败再走系统代理——这台机器上两种都遇到过毛病。"""
    last: Exception | None = None
    for trust_env in (False, True):
        try:
            resp = httpx.get(url, params=params, timeout=TIMEOUT, trust_env=trust_env)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:  # 网络问题一律降级
            last = exc
    raise RuntimeError(f"天气接口都不可用：{last}")


def _as_float(raw: object) -> float | None:
    try:
        return float(str(raw))
    except (TypeError, ValueError):
        return None


def fetch_amap() -> list[Forecast]:
    """高德：今天 + 未来 3 天。"""
    if not settings.amap_key:
        return []
    payload = _get(
        "https://restapi.amap.com/v3/weather/weatherInfo",
        {"key": settings.amap_key, "city": CITY_CODE, "extensions": "all"},
    )
    if str(payload.get("status")) != "1":
        return []
    forecasts = payload.get("forecasts") or []
    if not forecasts:
        return []
    out: list[Forecast] = []
    for cast in forecasts[0].get("casts", []):
        try:
            day = date.fromisoformat(str(cast.get("date")))
        except ValueError:
            continue
        out.append(
            Forecast(
                date=day,
                day_text=str(cast.get("dayweather") or ""),
                night_text=str(cast.get("nightweather") or ""),
                high=_as_float(cast.get("daytemp")),
                low=_as_float(cast.get("nighttemp")),
                source="amap",
            )
        )
    return out


def fetch_open_meteo(days: int = MAX_DAYS) -> list[Forecast]:
    """Open-Meteo：最多 16 天，这里只要 7 天。"""
    payload = _get(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": SHENZHEN[0],
            "longitude": SHENZHEN[1],
            "daily": "weather_code,precipitation_probability_max,temperature_2m_max,"
            "temperature_2m_min",
            "timezone": "Asia/Shanghai",
            "forecast_days": days,
        },
    )
    daily = payload.get("daily") or {}
    times = daily.get("time") or []
    out: list[Forecast] = []
    for i, raw_day in enumerate(times):
        try:
            day = date.fromisoformat(str(raw_day))
        except ValueError:
            continue
        code = (daily.get("weather_code") or [None])[i]
        text = WMO_TEXT.get(int(code), "未知") if code is not None else "未知"
        out.append(
            Forecast(
                date=day,
                day_text=text,
                night_text=text,
                high=_as_float((daily.get("temperature_2m_max") or [None])[i]),
                low=_as_float((daily.get("temperature_2m_min") or [None])[i]),
                precip=(daily.get("precipitation_probability_max") or [None])[i],
                source="open-meteo",
            )
        )
    return out


def forecast_map(force: bool = False) -> dict[date, Forecast]:
    """把两级来源并成一张「日期 → 天气」表，高德优先，Open-Meteo 补空。"""
    global _cache
    stamp, cached = _cache
    if not force and cached and time.time() - stamp < CACHE_TTL:
        return cached

    table: dict[date, Forecast] = {}
    for loader in (fetch_amap, fetch_open_meteo):
        try:
            for item in loader():
                table.setdefault(item.date, item)
        except (RuntimeError, KeyError, IndexError):
            continue  # 一个源挂了不影响另一个
    _cache = (time.time(), table)
    return table


def window() -> list[date]:
    """能查的日期范围：今天起 7 天。"""
    today = datetime.now().date()
    return [today + timedelta(days=i) for i in range(MAX_DAYS)]


def forecast_for(day: date) -> Forecast | None:
    """某一天的具体预报；超出 7 天或接口全挂时返回 None。"""
    if day not in window():
        return None
    return forecast_map().get(day)


def available_dates() -> list[str]:
    """前端用来提示「哪几天能自动查」——按接口真实返回，不是固定 7 天。"""
    table = forecast_map()
    return [d.isoformat() for d in sorted(table) if d in set(window())]


def reset_cache() -> None:
    """测试用：清掉缓存，别让一条用例污染下一条。"""
    global _cache
    _cache = (0.0, {})
