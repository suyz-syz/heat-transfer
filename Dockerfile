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

# 复制计算核心、服务入口与 Web GUI
COPY kiln_ht ./kiln_ht
COPY server.py .
COPY app.py .
COPY .streamlit ./.streamlit

# 暴露 API 服务端口 (8000) 与 Streamlit Web GUI 端口 (8501)
EXPOSE 8000 8501

# 通过 supervisord 同时启动 FastAPI 与 Streamlit 两个服务
CMD ["supervisord", "-c", "/app/supervisord.conf"]
