# syntax=docker/dockerfile:1

# ---- 基于轻量级 Python 官方镜像 ----
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先复制依赖清单，利用 Docker 层缓存加速迭代构建
COPY requirements-server.txt .
RUN pip install -r requirements-server.txt

# 复制计算核心与服务入口
COPY kiln_ht ./kiln_ht
COPY server.py .

# 暴露 API 服务端口
EXPOSE 8000

# 启动 FastAPI 服务
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
