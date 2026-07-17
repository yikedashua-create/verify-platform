# 客票验真平台 - Streamlit 单体部署
# 一锅炖: Streamlit + 15 航司 adapter + Playwright,一个端口搞定
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

# Streamlit 单端口 (Railway / Hugging Face / Streamlit Cloud 都默认 8501)
EXPOSE 8501

# 跑 Streamlit 单体应用
CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
