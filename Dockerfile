# 多阶段构建：先把依赖装成 wheel 缓存，再拷进运行镜像，镜像更小、重建更快。
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////app/data/chenke.db

WORKDIR /app
COPY --from=builder /install /usr/local

COPY algo ./algo
COPY backend ./backend
COPY web ./web
COPY data ./data
COPY scripts ./scripts
COPY pyproject.toml ./

# 非 root 运行
RUN mkdir -p /app/data && useradd -m -u 10001 app && chown -R app /app
USER app

EXPOSE 8000

# 启动时先把地点表灌进库（幂等），再起服务
CMD ["sh", "-c", "python -m scripts.seed && python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000"]
