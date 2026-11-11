"""应用配置。所有可调参数集中在这里，通过环境变量或 .env 覆盖。"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    app_name: str = "尘客"
    app_version: str = "0.1.0"

    # 默认用 SQLite，零依赖即可跑起来；部署时改成 postgresql+psycopg://...
    database_url: str = f"sqlite:///{(BASE_DIR / 'chenke.db').as_posix()}"

    # 前端开发时跨域用；生产环境挂同域可以保持 "*"
    cors_origins: str = "*"

    # 推荐时最多枚举多少个候选地点（池子越大越慢）
    pool_size: int = 24
    # 默认活动时间窗（分钟）
    window_minutes: int = 360
    # 一个局最多几个人
    max_members: int = 12

    # 高德 Key。留空则算法走内置估算，不依赖网络
    amap_key: str = ""

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


settings = Settings()
