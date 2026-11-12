"""FastAPI 入口。

启动：
    uvicorn app.main:app --app-dir backend --reload
"""

from __future__ import annotations

import socket
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR, settings
from .db import init_db
from .routers import groups, plans, pois, weather


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
app.include_router(weather.router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """把 Pydantic 的原始错误列表压成一句人话。

    原始响应长这样，直接甩给用户没人看得懂：
        [{"type":"int_parsing","loc":["path","member_id"],"msg":"Input should be a valid integer",...}]
    """
    readable = []
    for err in exc.errors()[:3]:
        loc = ".".join(str(p) for p in err.get("loc", ()) if p not in ("body", "path", "query"))
        readable.append(f"{loc + ' ' if loc else ''}{err.get('msg', '取值不合法')}")
    return JSONResponse(
        status_code=422,
        content={"detail": "参数不对 · " + "；".join(readable)},
    )


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    """部署健康检查。GitHub Actions 和容器探针都用它。"""
    return {"status": "ok", "app": settings.app_name, "version": settings.app_version}


def _lan_ips() -> list[str]:
    """本机的局域网 IPv4（尽力而为，拿不到就返回空列表）。

    用途：用户用 127.0.0.1 打开页面时，前端可以把「该发给朋友的地址」显示出来，
    省得他们对着 localhost 链接发呆。
    """
    ips: set[str] = set()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("223.5.5.5", 80))  # 不会真的发包，只让系统选出出口网卡
            ips.add(sock.getsockname()[0])
        finally:
            sock.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addr = info[4][0]
            if not addr.startswith("127."):
                ips.add(addr)
    except OSError:
        pass
    return sorted(ips)


@app.get("/api/netinfo", tags=["meta"])
def netinfo() -> dict:
    """本机可用于分享的局域网地址。纯读操作，不暴露任何敏感信息。"""
    return {"lan_ips": _lan_ips()}


# 静态前端（web/）。放在最后注册，避免抢走 /api 路由。
_web_dir = BASE_DIR / "web"
if _web_dir.exists():
    app.mount("/", StaticFiles(directory=str(_web_dir), html=True), name="web")
else:  # 只跑 API 时也能用

    @app.get("/", include_in_schema=False)
    def _root() -> RedirectResponse:
        return RedirectResponse(url="/docs")
