# Dockerfile for verify-platform
# 部署到 Railway / Hugging Face Spaces / 任何支持 Docker 的平台
#
# 关键:
# - 装 Playwright Chromium + Linux 系统依赖(xm-mf-ticket-verify 需要)
# - 不打 .exe(那是 desktop 版,见 build.spec)
# - 容器内直接跑 streamlit

FROM python:3.11-slim

# ============================================
# 1. 系统依赖(Playwright Chromium 需要的库)
# ============================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Playwright 核心库
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libxkbcommon0 \
    libcups2 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 libdrm2 libxfixes3 libxshmfence1 \
    # Streamlit / data 持久化工具
    tini curl \
    # 清理
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ============================================
# 2. Python 依赖
# ============================================
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ============================================
# 3. Playwright Chromium(2026-07-28 接入 xm-mf-ticket-verify 必须)
# ============================================
RUN python -m playwright install chromium

# ============================================
# 4. 复制代码
# ============================================================
COPY . .

# ============================================================
# 5. 健康检查(Railway 会用)
# ============================================================
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# ============================================================
# 6. 启动 streamlit
# ============================================================
# 用 tini 收信号,容器内 Ctrl+C 干净退出
# --server.address=0.0.0.0 让外部能访问(Railway 必须)
# --server.headless=true 不在容器内弹浏览器
EXPOSE 8501
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--server.enableCORS=false", \
     "--server.enableXsrfProtection=false", \
     "--browser.gatherUsageStats=false"]

# 数据持久化提示(部署平台要配 Volume 挂载 /app/data):
# - Railway:Settings → Volumes → Mount Path = /app/data
# - HuggingFace:Spaces Settings → Persistent Storage
# 不挂载 = 容器重启 cookie/secrets 全丢
