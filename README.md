# 客票验真平台 (P0 MVP)

把原来 `客票验真工具.py` 单文件桌面工具，迁成 web 平台。

## 架构

```
verify-platform/
├── airlines/          # 航司适配器(每航司一个文件)
│   ├── base.py        # 抽象基类
│   ├── f9.py          # F9 边疆
│   └── __init__.py    # 注册表 REGISTRY
├── backend/
│   └── app.py         # FastAPI 入口
├── frontend/
│   └── app.py         # Streamlit 页面
├── requirements.txt
└── README.md
```

## 启动

```powershell
# 1. 装依赖
pip install -r requirements.txt

# 2. 启后端 (终端 1)
python backend/app.py

# 3. 启前端 (终端 2)
streamlit run frontend/app.py
```

浏览器开 http://localhost:8501

## P0 范围

- [x] adapter 抽象接口
- [x] F9 边疆航司端到端跑通
- [x] FastAPI 框架
- [x] Streamlit 页面
- [ ] 11 个航司迁移 (P1)
- [ ] 历史记录 (P2)
- [ ] 部署 (P2)

## 加新航司

1. `airlines/` 新建一个 `xx.py`，继承 `AirlineAdapter` 实现 `_call_api` + `_parse`
2. 在 `airlines/__init__.py` 的 `REGISTRY` 注册
3. 完事，不用动 FastAPI / Streamlit
