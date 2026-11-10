"""数据库连接与会话管理。

用同步 SQLAlchemy 2.0：这个项目的并发量是一个群十几个人，
同步 + SQLite 完全够用，而且调试栈更短、评委更容易看懂。
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


connect_args = {"check_same_thread": False} if settings.is_sqlite else {}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    echo=False,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每个请求一个会话，请求结束自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """建表。生产环境应改用 Alembic 迁移，这里为了降低上手成本直接 create_all。"""
    from . import models  # noqa: F401  确保模型被注册

    Base.metadata.create_all(bind=engine)
