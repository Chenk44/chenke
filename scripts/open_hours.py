"""把高德的 `open_time` 字符串解析成 (开门, 打烊) 两个小数小时。

高德给的格式很杂，实测过的几种：

    09:30-22:00
    08:30-11:30 13:30-17:00     # 中午休息
    24小时营业
    周一至周日 10:00-22:00
    全天

多段营业时间取「最早的开门 + 最晚的打烊」，也就是包络。这样做的代价是
中午休息的馆子在午休时段会被当成开着——比反过来（把全天营业的馆子判成关门）
要安全：宁可多推一个，也不要凭空砍掉一个本来能去的地方。

打烊时间用 `> 24` 表示跨零点（凌晨两点打烊 = 26），和 `algo/types.py: is_open_at` 对应。
"""

from __future__ import annotations

import re

# 全表最粗的先验：高德没给营业时间时按品类兜底
DEFAULT_HOURS: dict[str, tuple[float, float]] = {
    "公园": (0.0, 24.0),
    "展览": (10.0, 22.0),
    "影院": (10.0, 24.0),
    "餐饮": (11.0, 22.0),
    "咖啡": (8.0, 22.0),
    "夜生活": (17.0, 26.0),
    "玩乐": (10.0, 22.0),
}

# 名字里带这些字眼的，按户外场所处理：基本全天可去
OUTDOOR_WORDS = (
    "公园",
    "绿道",
    "栈道",
    "湿地",
    "海滨",
    "海边",
    "沙滩",
    "海滩",
    "登山",
    "爬山",
    "露天",
    "摩天轮",
    "户外",
)  # 别放「山」「广场」：会把「陈记山水客家菜」「金光华广场」判成户外

# 名字里带这些字眼的，按夜宵处理
LATE_NIGHT_WORDS = ("夜市", "大排档", "夜宵", "酒吧", "清吧", "livehouse", "Livehouse")

_TIME = re.compile(r"(\d{1,2}):(\d{2})")
_ALL_DAY = re.compile(r"24\s*小时|全天|全天候")
_OFF_DAY = re.compile(r"^\s*(全天)?\s*(休息|不营业|暂停营业)\s*$")


def _to_hour(hh: str, mm: str) -> float:
    return int(hh) + int(mm) / 60.0


def parse_open_time(text: str | None) -> tuple[float, float] | None:
    """解析高德的营业时间；认不出来就返回 None，交给调用方兜底。"""
    if not text:
        return None
    s = text.strip()
    if not s or _OFF_DAY.match(s):
        return None
    if _ALL_DAY.search(s) and not _TIME.search(s):
        return (0.0, 24.0)

    stamps = [(int(h), int(m)) for h, m in _TIME.findall(s)]
    if len(stamps) < 2:
        return None

    spans: list[tuple[float, float]] = []
    for i in range(0, len(stamps) - 1, 2):
        start = _to_hour(*stamps[i])
        end = _to_hour(*stamps[i + 1])
        if end <= start:  # 18:00-02:00 这种
            end += 24.0
        spans.append((start, end))

    if not spans:
        return None
    opens = min(s for s, _ in spans)
    closes = max(e for _, e in spans)
    if closes <= opens:
        return None
    # 一天里不可能开超过 24 小时；超过说明解析到了「周一-周日」之类的时间段
    if closes - opens > 24.0:
        closes = opens + 24.0
    return (opens, min(closes, 26.0))


def default_hours(name: str, category: str) -> tuple[float, float]:
    """高德没给时间时的兜底：先看名字，再看品类。"""
    lowered = name.lower()
    if any(w in name for w in LATE_NIGHT_WORDS) or "livehouse" in lowered:
        return DEFAULT_HOURS["夜生活"]
    if any(w in name for w in OUTDOOR_WORDS):
        return DEFAULT_HOURS["公园"]
    return DEFAULT_HOURS.get(category, (0.0, 24.0))
