# 客票验真平台 🎫

多航司客票验真工具,原 `客票验真工具.py`(PyInstaller GUI 单文件)迁移到 Web 平台。

**架构**:Streamlit 单体应用,内嵌 15 航司 adapter,直接调用,无后端 API 层。
**部署**:Dockerfile,任何支持 Docker 的平台都能跑(Railway / Hugging Face / Render / Fly.io)。

---

## 支持的 15 个航司

| 代码 | 航司 | 访问方式 | 备注 |
|------|------|---------|------|
| F9 | Frontier Airlines | 公网 API | 美国 |
| IJ | Spring Airlines Japan (日本春秋) | 公网 API | |
| MM | Peach Aviation (乐桃) | 需登录 (bearer) | |
| 9C | Spring Airlines (春秋) | 需登录 (bearer) | |
| SL | Thai Lion Air (狮航) | 需登录态 (session) | |
| HX | Hong Kong Airlines (港航) | 内网网关 | |
| MF | XiamenAir (厦门航) | 内网网关 | |
| FR | Ryanair | 内网网关 | |
| VJ | VietJet Air (越捷) | 内网网关 | |
| FY | Firefly | 内网网关 | |
| AQ | 9 Air (九元) | 内网网关 | |
| GQ | Gameco | 内网网关 | |
| 5J | Cebu Pacific (宿务) | 内网网关 | |
| DD | Nok Air (皇雀) | 内网网关 | 姓字段 `passName` |
| OD | Batik Air (峇迪) | 内网网关 | |

**8 个内网网关航司**走 `http://172.18.247.238:32000/<航司>_*`,姓字段统一用 `passName`(不要翻译成 `lastName`)。

---

## 本地开发

```bash
pip install -r requirements.txt
playwright install chromium
streamlit run app.py
```

浏览器开 `http://localhost:8501`。

---

## 部署

任何支持 Docker 的平台都行。详细步骤见 [DEPLOY.md](DEPLOY.md)。

最简单路径:**Hugging Face Spaces**(Streamlit SDK,免信用卡,永久 URL)。
次简单:**Railway**(Dockerfile 自动检测,$5/月免费额度,自动重 build)。

---

## 新增航司

1. 在 `airlines/` 新建 `xxx.py`,继承 `AirlineAdapter`,实现 `name` / `code` / `api_url` / `form_fields` / `_call_api` / `_parse`
2. 在 `airlines/_official_urls.py` 加 `xxx: "https://..."` (验真页面 URL)
3. 在 `airlines/__init__.py` 的 `REGISTRY` 加一行
4. 重启 Streamlit(改代码不自动 reload,因为是 Streamlit rerun,adapter 实例化在 `list_airlines()` 调用时)

---

## 项目结构

```
verify-platform/
├── app.py                     # Streamlit 单体入口
├── airlines/                  # 15 航司 adapter
│   ├── __init__.py            # REGISTRY
│   ├── base.py                # AirlineAdapter 抽象类
│   ├── _official_urls.py      # 验真 URL 集中管理
│   └── {f9,ij,mm,ch,sl,...}.py
├── Dockerfile
├── requirements.txt
└── DEPLOY.md
```
