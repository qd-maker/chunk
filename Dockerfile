# ---------- 1. 构建前端（React + Vite → /src/static） ----------
FROM node:22-alpine AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---------- 2. 运行后端（FastAPI，同时提供前端页面） ----------
FROM python:3.12-slim
# TZ：“今天到期”按北京时间零点算；不设的话容器是 UTC，早上 8 点前的练习会算到前一天
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data TZ=Asia/Shanghai
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY --from=web /src/static ./static
# 固定 UID 1000：服务器上的数据目录要 chown 1000:1000
RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown app /data
USER app
EXPOSE 8781
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8781/api/health', timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8781", "--proxy-headers", "--forwarded-allow-ips", "*"]
