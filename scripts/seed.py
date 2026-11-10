"""把 data/pois_shenzhen.csv 灌进数据库。

用法：
    python -m scripts.seed           # 增量更新（会覆盖同 id 的字段）
    python -m scripts.seed --reset   # 先清空再灌，适合改完表结构
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# ROOT 用于 `algo`，ROOT/backend 用于 `app`——全项目统一这一种 import 方式，
# 避免 `app.db` 和 `backend.app.db` 被当成两个模块、建出两个 engine。
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

# Windows 的 cmd / PowerShell 默认是 GBK，直接 print 中文和 ✅ 会 UnicodeEncodeError。
# 这不是装饰问题：灌数据是使用者第一步，第一步就崩会很劝退。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):  # 老 Python 或重定向到不支持的对象
    pass

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import POIRecord  # noqa: E402

from algo.loader import POIDataError, load_pois  # noqa: E402


def seed(reset: bool = False) -> int:
    pois = load_pois()
    init_db()

    with SessionLocal() as db:
        if reset:
            db.query(POIRecord).delete()
            db.commit()

        existing = {r.id: r for r in db.query(POIRecord).all()}
        created = updated = 0

        for poi in pois:
            rec = existing.get(poi.id)
            if rec is None:
                rec = POIRecord(id=poi.id)
                db.add(rec)
                created += 1
            else:
                updated += 1

            rec.name = poi.name
            rec.area = poi.area
            rec.district = poi.district
            rec.category = poi.category
            rec.lat = poi.lat
            rec.lng = poi.lng
            rec.avg_price = poi.avg_price
            rec.rating = poi.rating
            rec.indoor = poi.indoor
            rec.quiet = poi.quiet
            rec.min_people = poi.min_people
            rec.max_people = poi.max_people
            rec.kid_friendly = poi.kid_friendly
            rec.need_booking = poi.need_booking
            rec.queue = poi.queue
            rec.tags = "|".join(poi.tags)
            rec.blurb = poi.blurb

        db.commit()

    print(f"✅ 地点库已更新：新增 {created} 条，更新 {updated} 条，共 {len(pois)} 条")
    return created + updated


def main() -> int:
    parser = argparse.ArgumentParser(description="灌入深圳地点数据")
    parser.add_argument("--reset", action="store_true", help="先清空再灌")
    args = parser.parse_args()

    try:
        seed(reset=args.reset)
    except POIDataError as exc:
        print(f"❌ 数据表有问题：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
