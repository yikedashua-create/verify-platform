# 客票验真平台 🎫 (桌面版)

多航司客票验真工具,原 `客票验真工具.py`(PyInstaller GUI 单文件 2745 行)**升级**为现代化桌面应用:

- **Streamlit 漂亮 Web UI**(不再是老 tkinter)
- **单文件 .exe 安装**(双击即用,不用装 Python)
- **自动检查更新**(启动时检查 GitHub Releases)
- **集中代码管理** + GitHub Actions 自动 build

**架构**:每用户本机跑一个 .exe(双击 → 自动开浏览器 → 看到 UI),**不需要任何服务器**。

---

## 团队使用流程

### 第一次安装(每用户做一次)

1. 浏览器开 **`https://github.com/yikedashua-create/verify-platform/releases/latest`**
2. 下载 `客票验真.exe`(约 200-300 MB,含 Playwright)
3. 双击 `客票验真.exe`
4. 第一次启动会解压 + 装环境(约 1-2 分钟,**只此一次**)
5. 自动开浏览器到 `http://localhost:8501` → 看到 "🎫 客票验真平台"

### 日常使用

- 双击 `客票验真.exe` → 浏览器自动开 → 选航司验真
- 关闭浏览器 + .exe 控制台窗口,服务停止

### 升级(自动)

- 每次启动自动检查 GitHub Releases
- 有新版时侧栏顶部显示 **"🆕 新版本 vX.Y.Z 可用"**
- 点 "⬇️ 立即下载" → 浏览器跳到 GitHub 下载页 → 替换 .exe 即可

---

## 支持的 15 个航司

| 代码 | 航司 | 备注 |
|------|------|------|
| F9 | Frontier Airlines | 公网 API |
| IJ | Spring Airlines Japan (日本春秋) | 公网 API |
| MM | Peach Aviation (乐桃) | 需登录 (bearer) |
| 9C | Spring Airlines (春秋) | 需登录 (bearer) |
| SL | Thai Lion Air (狮航) | 需登录态 (session) |
| HX | Hong Kong Airlines (港航) | 内网网关 |
| MF | XiamenAir (厦门航) | 内网网关 |
| FR | Ryanair | 内网网关 |
| VJ | VietJet Air (越捷) | 内网网关 |
| FY | Firefly | 内网网关 |
| AQ | 9 Air (九元) | 内网网关 |
| GQ | Gameco (Sky Express) | 公网 Sabre API |
| 5J | Cebu Pacific (宿务) | 内网网关 |
| DD | Nok Air (皇雀) | 内网网关 |
| OD | Batik Air (峇迪) | 内网网关 |

**8 个内网关航司**走 `http://172.18.247.238:32000/*`,姓字段统一用 `passName`(不要翻译成 `lastName`)。

**为什么必须本机跑**:`172.18.247.238` 是公司内网地址,公网 PaaS(Railway / HF / 阿里云)都访问不到。所以采用**每用户本机跑 .exe**的模式 —— 你的电脑在你公司内网,天然能访问 172 网关。

---

## 开发流程

### 本地开发(直接跑源码)

```bash
# 装依赖
pip install -r requirements.txt
playwright install chromium

# 启 app (开发模式,改代码自动 reload)
streamlit run app.py

# 浏览器开 http://localhost:8501
```

### 发布新版(打 .exe)

1. 改代码,本地测好
2. `git add . && git commit -m "xxx"`
3. `git push origin main` — 推代码到 GitHub
4. 打 tag 触发自动 build:
   ```bash
   git tag v1.0.1
   git push origin v1.0.1
   ```
5. GitHub Actions 自动:
   - 装依赖 + 跑 PyInstaller
   - 出 `客票验真.exe` (~200-300 MB)
   - 发到 GitHub Releases
6. 团队用户**下次启动 .exe 收到更新提示**,点 "立即下载" 就拿到新版

### 首次 build(测试 workflow)

1. GitHub 仓库 → **Actions** 标签
2. 选 "Build Windows .exe" workflow
3. 点 "Run workflow" → 选 main → Run
4. 等 3-5 分钟,下载 `客票验真.exe` artifact
5. 测一下能不能跑,跑通就正式发版

---

## 项目结构

```
verify-platform/
├── app.py                      # Streamlit 应用(15 航司 UI)
├── main.py                     # .exe 启动入口(打包入口)
├── auto_updater.py             # 检查 GitHub Releases 写更新文件
├── build.spec                  # PyInstaller 打包配置
├── requirements.txt
├── airlines/                   # 15 航司 adapter
│   ├── __init__.py             # REGISTRY
│   ├── base.py                 # AirlineAdapter 抽象类
│   ├── _official_urls.py       # 验真 URL 集中管理
│   └── {f9,ij,mm,ch,sl,hx,mf,fr,vj,fy,aq,gq,5j,dd,od}.py
└── .github/
    └── workflows/
        └── build.yml           # GitHub Actions 自动 build
```

---

## 新增航司

1. 在 `airlines/` 新建 `xxx.py`,继承 `AirlineAdapter`,实现 `name` / `code` / `api_url` / `form_fields` / `_call_api` / `_parse`
2. 在 `airlines/_official_urls.py` 加 `xxx: "https://..."` (验真页面 URL)
3. 在 `airlines/__init__.py` 的 `REGISTRY` 加一行
4. 改完 push → GitHub Actions 自动 build 新 .exe → 团队下次启动收到

---

## 故障排查

| 问题 | 解决 |
|------|------|
| 双击 .exe 闪退 | 看控制台窗口错误,通常是 Playwright 没装好(重新装: `playwright install chromium`) |
| 浏览器没自动开 | 手动开 `http://localhost:8501` |
| 选航司后查询超时 | 检查公司内网 172.18.247.238 是否能访问 |
| 启动慢(10+ 秒) | 第一次启动解压,后续秒开 |
| .exe 太大(>500MB) | 正常,Playwright chromium 占大头 |
| 看不到更新提示 | 首次启动可能要等 1-2 分钟(后台线程检查 GitHub) |
