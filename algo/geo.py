"""距离与通行时间估算。

生产环境应当用高德路径规划 API 预计算「商圈 × 商圈」的时间矩阵并缓存到数据库
（见 `docs/ALGORITHM.md` 的「为什么预计算」一节）。这里保留一个纯函数的兜底估算，
好处是：离线可跑、单元测试稳定、CI 不需要网络和 API Key。
"""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0

# 深圳的粗略通行参数，来源于经验值，仅用于兜底估算。
METRO_SPEED_KMH = 26.0  # 含站停的地铁平均速度
METRO_DETOUR = 1.35  # 地铁线路绕行系数
METRO_ACCESS_MIN = 8.0  # 进出站 + 步行接驳
DRIVE_SPEED_KMH = 24.0  # 市区驾车平均速度（含拥堵）
DRIVE_DETOUR = 1.25
DRIVE_PARK_MIN = 8.0  # 找车位 + 停车
WALK_SPEED_KMH = 4.8
WALK_MAX_KM = 1.2


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """两点球面距离（公里）。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def estimate_travel_minutes(
    lat1: float,
    lng1: float,
    lat2: float,
    lng2: float,
    has_car: bool = False,
) -> float:
    """估算从一个点到另一个点需要多少分钟。

    短距离优先步行，有车优先驾车，否则按地铁估算。
    返回值已经包含接驳/停车等固定开销，可以直接累加进方案总耗时。
    """
    km = haversine_km(lat1, lng1, lat2, lng2)
    if km <= WALK_MAX_KM:
        return max(2.0, km / WALK_SPEED_KMH * 60.0)
    if has_car:
        return km * DRIVE_DETOUR / DRIVE_SPEED_KMH * 60.0 + DRIVE_PARK_MIN
    return km * METRO_DETOUR / METRO_SPEED_KMH * 60.0 + METRO_ACCESS_MIN


def distance_decay(minutes: float, half_life: float = 25.0) -> float:
    """把通行时间转换成 0~1 的「可达性」分数。

    用指数衰减而不是线性，是因为人对 10 分钟和 20 分钟的差别很敏感，
    对 70 分钟和 80 分钟几乎没有感觉。half_life 是分数降到一半所需的分钟数。
    """
    if minutes <= 0:
        return 1.0
    return 0.5 ** (minutes / half_life)
