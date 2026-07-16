# 上线部署指南 (Streamlit Cloud + Render)

## 架构

```
用户浏览器 ──→ Streamlit Cloud (前端) ──→ Render (后端 + Playwright)
                       免费                     免费层
```

**前端**（Streamlit Cloud）—— 跑 `frontend/app.py`，从 secrets 读后端 URL
**后端**（Render）—— 跑 `backend/app.py` + Playwright，用 Dockerfile build

---

## 步骤 1：推到 GitHub

```powershell
cd C:\Users\admin\verify-platform

# 1.1 初始化 git
git init
git add .
git commit -m "init: verify-platform"

# 1.2 在 github.com 创建一个新仓库 (名字随便,例如 verify-platform)
#    不要勾选 README / .gitignore / license (本地已有)

# 1.3 推上去 (替换成你的 GitHub 用户名 + 仓库名)
git remote add origin https://github.com/526147588-afk/verify-platform.git
git branch -M main
git push -u origin main
```

---

## 步骤 2：部署后端到 Render

1. 去 https://render.com 用 GitHub 登录
2. **New +** → **Web Service**
3. 选刚 push 的 `verify-platform` 仓库 → **Connect**
4. 配置：
   - **Name**: `verify-platform-api`（或随便）
   - **Region**: Singapore（离大陆近）/ Oregon（免费层有时强制这里）
   - **Branch**: `main`
   - **Root Directory**: 留空
   - **Runtime**: **Docker**
   - **Dockerfile Path**: `Dockerfile`（自动）
   - **Docker Context**: 留空
   - **Plan**: **Free**
5. **Advanced** → 加环境变量（可选）:
   - `PYTHONUNBUFFERED=1` （日志更友好）
6. 点 **Create Web Service**
7. 等 5-10 分钟 build（Playwright + Chromium 下载）
8. 部署成功后 Render 给你一个 URL，类似 `https://verify-platform-api.onrender.com`

**测试后端**：
- 浏览器开 `https://verify-platform-api.onrender.com/health` 应该看到 `{"status":"ok"}`
- 浏览器开 `https://verify-platform-api.onrender.com/airlines` 应该看到 JSON

⚠️ **冷启动警告**：Render 免费层 15 分钟无访问会休眠，下次访问要等 30-60 秒

---

## 步骤 3：部署前端到 Streamlit Cloud

1. 去 https://share.streamlit.io 用 GitHub 登录
2. **New app**
3. 配置：
   - **Repository**: `526147588-afk/verify-platform`
   - **Branch**: `main`
   - **Main file path**: `frontend/app.py`
   - **App URL**: 随便起个名字,如 `xu-zhe-verify`
4. **Advanced settings** → **Secrets**:
   ```toml
   api_base = "https://verify-platform-api.onrender.com"
   ```
   ⚠️ **不要带尾部斜杠 /！不要带 `/verify` 之类！就是根 URL**
5. 点 **Deploy**
6. 等 2-5 分钟装依赖
7. 完成后给你 URL，类似 `https://xu-zhe-verify.streamlit.app`

---

## 步骤 4：测试

- 浏览器开前端 URL，应该看到 15 个航司
- 选个航司查票（**第一次要等 30-60 秒**，后端在冷启动）
- 查成功后生成凭证 → 下载 PNG

---

## 改代码后怎么更新

- **前端**：推 GitHub → Streamlit Cloud 自动检测 commit → 1-2 分钟自动部署
- **后端**：推 GitHub → Render 自动检测 commit → 3-5 分钟重新 build（要重下 Chromium 镜像层缓存，所以很快）

---

## 排错

| 现象 | 原因 | 解决 |
|------|------|------|
| Streamlit Cloud 页面空白 | secrets 配错 | Settings → Secrets 检查 `api_base` |
| Streamlit Cloud `Connection refused` | 后端没部署 / Render URL 错 | 浏览器直接访问后端 URL 看是否 200 |
| Render `Application failed to start` | Dockerfile 写错 | Render → Logs 看详细错误 |
| 凭证生成慢 | Render 冷启动 | 第一次查后等 30-60s |
| Streamlit Cloud `ModuleNotFoundError: playwright` | 前端不需要 playwright | 应该不出现,正常 |
