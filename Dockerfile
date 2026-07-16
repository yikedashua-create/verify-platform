# 客票验真平台 - 单容器部署 (后端 + 前端)
FROM python:3.11-slim

# Playwright 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget ca-certificates \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 装 Python 依赖 (先装依赖层缓存,改代码不重装)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 装 Playwright Chromium (单独步骤,镜像层缓存)
RUN playwright install chromium

# 拷代码
COPY . .

# 暴露端口: 8002 后端 / 8501 前端
EXPOSE 8002 8501

# 单容器同时跑后端 + 前端
CMD ["sh", "-c", "python backend/app.py & streamlit run frontend/app.py --server.port=8501 --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false"]
