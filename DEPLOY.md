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

## 方案 2: Railway(免信用卡,简单)

跟 Render 体验类似,不用绑卡。$5/月免费额度,够一个轻量 Streamlit 跑满月。

### 步骤

1. **登录 Railway**
   - 浏览器开 `https://railway.app`
   - 右上角 **Login** → **Login with GitHub** → 授权

2. **新建项目**
   - 顶 **+ New Project** → **Deploy from GitHub repo**
   - 选 `<your-github>/verify-platform`
   - Railway 自动检测 Dockerfile,开始 build

3. **生成公网 URL**
   - 进入 service → **Settings** 标签 → **Networking** 区域
   - 点 **Generate Domain** → 拿到 `https://verify-platform.up.railway.app`

4. **等 build 完成**
   - 顶上 Logs 标签看进度,Playwright 装 chromium 慢(2-5 分钟)
   - 状态变 **Success** → 浏览器开 URL 验证

### 注意

- **5 美元额度耗完会停**:重置在每月 1 号(注册日起算)
- **不要 commit secrets**:把任何 .env / secrets.toml 加进 .gitignore(已默认)
- **首次冷启动 5-15 秒**:free tier 不像 HF 那样强制休眠

---

## 方案 3: Render(要信用卡,跳过)

2023 年 4 月起强制绑卡验证(免费 plan 也要)。不推荐。

---

## 部署后验证

1. 浏览器开 URL → 看到 **"🎫 客票验真平台"** 标题
2. 侧栏航司列表应该有 **15 个**
3. 选个航司(比如 HX 港航)→ 填测试数据 → 点 "查询"
4. 等 5-10 秒 → 看到查询结果
5. 如果有 flight_info,点 "一键生成凭证" → 下载 PNG

**测试用例**(随便挑一个跑通就行):
- HX 港航:票号 `123-4567890123` + 姓 `WONG` + 名 `TAI MAN`
- 9C 春秋:任意订单号
- MM 乐桃:任意票号(需要登录 token,先在 base.py 配)
