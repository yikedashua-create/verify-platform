# 部署指南

3 个推荐平台,按"易用性"排序。**首选 Hugging Face Spaces** —— 不要卡,5 分钟上线。

---

## 方案 1: Hugging Face Spaces(推荐 ⭐)

免信用卡,永久 URL,Streamlit 原生支持。

### 步骤

1. **登录 Hugging Face**
   - 浏览器开 `https://huggingface.co`
   - 右上角 **Sign in** → **Sign in with GitHub** → 授权你的 GitHub 账号

2. **创建 Space**
   - 浏览器开 `https://huggingface.co/new-space`
   - 填:
     - **Owner**: 你的 GitHub username
     - **Space name**: `verify-platform`
     - **License**: MIT
     - **SDK**: **Streamlit** ← 关键
     - **Space hardware**: **CPU basic - free**
   - 点 **Create Space**

3. **推送代码到 Space**
   - Space 创建后会给一个空 git 仓库:`https://huggingface.co/spaces/<owner>/verify-platform`
   - 推送方式:在 Space 页面顶上 **Files** → **Add file** → **Upload files**(直接拖整个项目)
   - 或者用 git 命令(SSH/HTTPS,凭据复用 GitHub 那把 SSH key)

4. **等 build + 启动**
   - Space 自动 build(2-5 分钟,装 Playwright 慢)
   - 顶上状态变 **Running** 后,URL `https://<owner>-verify-platform.hf.space` 可访问

### 注意

- **Playwright 在 Space 里需要 root**:`packages.txt` 加 chromium + fonts,`runtime.txt` 钉 Python 版本(可选,默认 3.11 OK)
- **首次冷启动 30-60 秒**:Space free tier 闲置会休眠

---

## 方案 2: Railway(免信用卡,简单) — 项目当前用 ⭐

跟 Render 体验类似,不用绑卡。$5/月免费额度,够一个轻量 Streamlit 跑满月。

**项目已配 Dockerfile + railway.json**(2026-07-28 接入 xm-mf-ticket-verify 后),直接 push 就触发部署。

### 步骤

1. **代码已推到 GitHub**(main 分支,commit 5069a5a+)
2. **Railway 触发部署**:
   - 浏览器开 `https://railway.app/dashboard`
   - 进 `carefree-radiance` 项目
   - 点 **Deploy** → 等 build(2-5 分钟,装 Chromium 慢)
3. **看 build 日志**:
   - 顶 **Logs** 标签,等出现 `You can now view your Streamlit app`
   - 看到 ✅ 表示 build 成功,服务在跑
4. **生成公网 URL**(已有就跳过):
   - 进入 service → **Settings** 标签 → **Networking** 区域
   - 点 **Generate Domain** → 拿到 `https://verify-platform-production.up.railway.app`

### 必配:环境变量 + Volume

**1. 环境变量(Railway → Variables)**:

| 变量 | 值 | 说明 |
|------|------|------|
| `MF_PASSWORDS_JSON` | `{"16673220623": "hmling33*", "18975297618": "XTpa8020"}` | JSON 格式,所有账号密码一次配齐 |

**2. 数据持久化 Volume**(重要!容器重启 = 全部数据丢):

| 路径 | 持久化 | 作用 |
|------|--------|------|
| `/app/data` | ✅ 必须 | `accounts.db`(cookie 缓存)+ verify_results.db |
| `/app/.streamlit` | ⚠️ 可选 | `secrets.toml`(用环境变量就**不需要**这个) |

**不挂 Volume 的后果**:容器重启 → cookie 全丢 → 用户得重新 ddddocr 登录。

**挂 Volume 步骤**:
- Railway → service → **Settings** → **Volumes** 区域
- 点 **+ New Volume** → 名字 `verify-data` → Mount Path 填 `/app/data`
- Apply → 自动重启服务

### 注意

- **5 美元额度耗完会停**:重置在每月 1 号(注册日起算)
- **不要 commit secrets**:把任何 .env / secrets.toml 加进 .gitignore(已默认,且 .dockerignore 排除)
- **首次冷启动 5-15 秒**:free tier 不像 HF 那样强制休眠
- **Health check**:Railway 用 `/_stcore/health` 端点,Streamlit 1.58+ 自带

---

## 方案 3: Render(要信用卡,跳过)

2023 年 4 月起强制绑卡验证(免费 plan 也要)。不推荐。

---

## 部署后验证

1. 浏览器开 URL → 看到 **"🎫 客票验真平台"** 标题
2. 侧栏航司列表应该有 **15 个**
3. 选 MF 厦门航司 → 填订单号 + 手机号 → 点 "查询"
4. 等 20-30 秒(自动登录 + 抓票号)→ 看到结果
5. 如果有 flight_info,点 "一键生成凭证" → 下载 PNG

**MF 自动验真测试用例**(2026-07-28 实测通过):
- 订单号: `202607271326379366` / 手机号: `16673220623`
- 订单号: `202607280305388738` / 手机号: `18975297618`
- 期望:票号 + 票状态(未使用/已使用/已退票/已改期)

**首次跑会触发 ddddocr 自动登录**(用环境变量 `MF_PASSWORDS_JSON` 配的密码)。
**之后 cookie 命中,21 秒出结果**。

---

## 关键文件清单(2026-07-28 接入 xm-mf-ticket-verify 后)

| 文件 | 作用 |
|------|------|
| `Dockerfile` | Railway 部署入口,装 Playwright + Chromium + 系统依赖 |
| `railway.json` | Railway build/deploy 配置(builder=DOCKERFILE, healthcheck, restart policy) |
| `.dockerignore` | 排除 `data/` / `secrets.toml` / `__pycache__/` 等敏感/临时文件 |
| `requirements.txt` | + pydantic / ddddocr / onnxruntime / pyyaml / loguru |
| `xm_mf_verify/` | 从 xm-mf-ticket-verify 拷过来的 10 个文件,负责 MF 自动验真 |
| `airlines/mf.py` | MF 厦门航司适配器,双模式(已知票号/只有订单号)+ 密码自动存 |
