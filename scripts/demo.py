"""命令行端到端演示：不打开浏览器也能看到「众口」在干什么。

用法：
    python -m scripts.demo

它会用一个临时数据库，建一个 5 人的局、填 5 组不同的偏好、跑一次推荐，
然后把方案、解释、每个人的满意度打印出来。适合答辩现场投屏，也适合快速验证改动。
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 必须在 import app 之前设置，否则 engine 会连到正式库
os.environ["DATABASE_URL"] = f"sqlite:///{ROOT / 'demo.db'}"
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

# Windows 控制台默认不是 UTF-8，直接 print 中文会 UnicodeEncodeError
with contextlib.suppress(AttributeError, OSError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

MEMBERS = [
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
]


def clock(offset_minutes: float) -> str:
    """方案时间线默认从下午 2 点开始。"""
    total = 14 * 60 + round(offset_minutes or 0)
    return f"{total // 60:02d}:{total % 60:02d}"


def rule(title: str = "") -> None:
    print("\n" + ("─" * 62))
    if title:
        print(title)
        print("─" * 62)


def main() -> None:
    db_path = ROOT / "demo.db"
    if db_path.exists():
        db_path.unlink()

    from scripts.seed import seed

    seed(reset=True)

    client = TestClient(app)

    health = client.get("/api/health").json()
    poi_count = len(client.get("/api/pois").json())
    print(f"众口 v{health['version']} · 地点数 {poi_count}")

    rule("① 建局")
    group = client.post(
        "/api/groups",
        json={
            "name": "周六下午，五个人",
            "origin_area": "海岸城",
            "weather": "rain",
            "budget": 150,
            "window_minutes": 360,
        },
    ).json()
    print(
        f"邀请码 {group['code']} · 从 {group['origin_area']} 出发 · 下雨 · 人均 ≤ ¥{group['budget']:.0f}"
    )

    rule("② 五个人各填各的")
    for spec in MEMBERS:
        nickname = spec.pop("nickname")
        member = client.post(
            f"/api/groups/{group['code']}/members", json={"nickname": nickname}
        ).json()
        payload = {"auto_parse": True, **{k: 0.5 for k in ("quiet", "price", "near")}, **spec}
        pref = client.put(f"/api/members/{member['id']}/preference", json=payload).json()
        hints = "、".join(pref["parsed_hints"]) or "（只用了滑杆）"
        spec["nickname"] = nickname
        print(
            f"  {nickname:<6} 安静 {pref['quiet']:.2f} 花钱 {pref['price']:.2f} "
            f"距离 {pref['near']:.2f}  读懂：{hints}"
        )

    rule("③ 生成方案")
    out = client.post(f"/api/groups/{group['code']}/recommend").json()

    for note in out["notes"]:
        print(f"  {note}")

    for i, plan in enumerate(out["plans"], 1):
        print(
            f"\n  方案 {i} · 共识 {(plan['consensus'] * 100):.0f}% · "
            f"全程约 {plan['total_minutes'] / 60:.1f} 小时"
        )
        for j, item in enumerate(plan["items"]):
            arrow = "  └→ " if j else "  "
            print(
                f"{arrow}{clock(item['offset_minutes'])}  {item['name']}"
                f"（{item['category']} · {item['area']} · 人均 ¥{item['avg_price']:.0f}）"
            )
            print(f"          {item['blurb']}")
        print(f"     {plan['explanation']}")
        per = "  ".join(f"{k} {v * 100:.0f}" for k, v in plan["per_member"].items())
        print(f"     每人满意度：{per}")

    rule("④ 群体排序的交叉验证")
    print(f"  两种聚合规则的一致度 {out['agreement'] * 100:.0f}%（越高说明结论越稳）\n")
    print(f"  {'地点':<22}{'共识':>6}{'平均':>6}{'最低':>6}{'Borda':>7}{'后悔':>6}")
    for p in out["top_pois"][:8]:
        print(
            f"  {p['id']:<22}{p['consensus'] * 100:>5.0f}%{p['mean'] * 100:>5.0f}%"
            f"{p['worst'] * 100:>5.0f}%{p['borda'] * 100:>6.0f}%{p['regret'] * 100:>5.0f}%"
        )

    rule("⑤ 投票")
    plans = client.get(f"/api/groups/{group['code']}/plans").json()["plans"]
    for member in client.get(f"/api/groups/{group['code']}").json()["members"][:3]:
        client.post(f"/api/plans/{plans[0]['id']}/vote", json={"member_id": member["id"]})
    votes = client.get(f"/api/groups/{group['code']}/votes").json()
    for v in votes:
        mark = " ← 票数最高" if v["winner"] else ""
        print(f"  方案 {v['plan_id']}：{v['votes']} 票 {'、'.join(v['voters'])}{mark}")

    rule()
    print("演示结束。清掉 demo.db 即可重跑：Remove-Item demo.db")
    print(f"数据库：{ROOT / 'demo.db'}")


if __name__ == "__main__":
    main()
