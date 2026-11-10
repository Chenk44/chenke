"""FastAPI 入口。

启动：
    uvicorn app.main:app --app-dir backend --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR, settings
from .db import init_db
from .routers import groups, plans, pois


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=f"{settings.app_name} API",
    version=settings.app_version,
    description=(
        "为一群人（而不是单个人）推荐去哪玩。\n\n"
        "核心接口是 `POST /api/groups/{code}/recommend`，"
        "它把所有人的偏好聚合成 3 个「地点组合 + 动线」方案。"
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(groups.router)
app.include_router(plans.router)
app.include_router(pois.router)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    """部署健康检查。GitHub Actions 和容器探针都用它。"""
    return {"status": "ok", "app": settings.app_name, "version": settings.app_version}


# 静态前端（web/）。放在最后注册，避免抢走 /api 路由。
_web_dir = BASE_DIR / "web"
if _web_dir.exists():
    app.mount("/", StaticFiles(directory=str(_web_dir), html=True), name="web")
else:  # 只跑 API 时也能用

    @app.get("/", include_in_schema=False)
    def _root() -> RedirectResponse:
        return RedirectResponse(url="/docs")
