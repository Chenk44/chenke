"""pytest 全局配置。

关键点：在导入 app 之前把 DATABASE_URL 指向测试库，
否则测试会写到开发用的 zhongkou.db 里，把你的演示数据搞花。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for path in (str(ROOT), str(ROOT / "backend")):
    if path not in sys.path:
        sys.path.insert(0, path)

TEST_DB = ROOT / "tests" / "_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"


@pytest.fixture()
def client():
    """每个测试一个干净的库，并预置地点数据。"""
    from app.db import Base, engine
    from app.main import app
    from fastapi.testclient import TestClient

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    from scripts.seed import seed

    seed()

    with TestClient(app) as c:
        yield c
