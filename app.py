"""客票验真平台 - Streamlit 单体应用

内嵌 15 航司 adapter,直接调不绕 HTTP
Streamlit 老手风格: 一锅炖,无 FastAPI
"""
import base64
import sys
import os
import streamlit as st

# 让 app.py 能 import 同级 airlines/ 目录
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from airlines import get_adapter, list_airlines
from airlines.ticket_generator import generate_ticket_images

def do_self_update(update_info: dict):
    """一键自更新 (2026-08-17 加):
    1. 下载新 exe 到 %TEMP%
    2. spawn detached helper 进程 (verify-platform.exe --_do_update)
    3. 当前 Streamlit 立即 os._exit 退出,文件句柄释放
    4. helper 等 5s → 删旧 exe → rename 新 → 启动新 exe
    """
    import subprocess
    import tempfile
    import urllib.request
    import time

    url = update_info['url']
    current_exe = sys.executable  # PyInstaller onefile 时 = .exe 路径
    new_exe_temp = os.path.join(tempfile.gettempdir(), "verify-platform-update.exe")

    progress = st.progress(0)
    status = st.empty()

    try:
        status.text("⏳ 正在下载新版本...")

        def report(count, block_size, total_size):
            if total_size > 0:
                pct = min(100, int(count * block_size * 100 / total_size))
                progress.progress(pct / 100)

        urllib.request.urlretrieve(url, new_exe_temp, reporthook=report)
        progress.progress(100)
        status.text("✅ 下载完成, 准备重启...")

        # spawn helper: 当前 exe 用 --_do_update 标志重新启动
        # 0x00000008 = DETACHED_PROCESS (独立, 不依附父进程 console)
        # 0x00000200 = CREATE_NEW_PROCESS_GROUP (Ctrl+C 不传播)
        creation_flags = 0x00000008 | 0x00000200
        subprocess.Popen(
            [current_exe, '--_do_update', current_exe, new_exe_temp],
            creationflags=creation_flags,
            close_fds=True,
        )

        time.sleep(2)
        status.text("🚀 即将关闭并启动新版本 (浏览器会自动重连)...")
        time.sleep(1)

        # 立即退出, 不走 atexit 清理 (文件句柄立即释放, helper 5s 后能删旧 exe)
        os._exit(0)
    except Exception as e:
        status.text(f"❌ 更新失败: {e}")
        progress.empty()


st.set_page_config(
    page_title="客票验真平台",
    page_icon="🎫",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 自动更新提示(后台线程写到临时文件,这里读)
try:
    from auto_updater import read_update_info, clear_update_info
    _update = read_update_info()
except Exception:
    _update = None
if _update:
    with st.sidebar.container(border=True):
        st.markdown(f"### 🆕 新版本 v{_update['latest']} 可用")
        st.caption(f"当前 v{_update.get('current', '?')} · 新版 {_update['size_mb']} MB")

        # 2026-08-17 加一键自更新
        # 在 PyInstaller onefile 模式 (sys.frozen) 下能直接替换当前 exe
        # 开发模式 (sys.frozen=False) 只能下载,不能自更新 (没有 .exe 路径)
        if getattr(sys, 'frozen', False):
            if st.button("🔄 立即更新并重启", use_container_width=True, type="primary", key="do_update"):
                do_self_update(_update)
        st.link_button(
            "⬇️ 仅下载 (zip)" if getattr(sys, 'frozen', False) else "⬇️ 立即下载新版本",
            _update["url"],
            use_container_width=True,
        )
        if st.button("忽略此版本", use_container_width=True, key="dismiss_update"):
            clear_update_info()
            st.rerun()

# 当前版本 (2026-08-17 加, 侧栏底部小字, 让用户知道自己在跑哪个版本)
st.sidebar.caption(f"📦 当前版本 v{os.environ.get('APP_VERSION', 'dev')}")

# 自定义 CSS
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #1E88E5 0%, #1565C0 100%);
        padding: 18px 28px;
        border-radius: 12px;
        margin-bottom: 18px;
        color: white;
        box-shadow: 0 2px 8px rgba(30, 136, 229, 0.2);
    }
    .main-header h1 { color: white !important; margin: 0; font-size: 26px; font-weight: 600; }
    .main-header p { margin: 4px 0 0 0; opacity: 0.9; font-size: 13px; }
    .badge { display: inline-block; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 600; margin-bottom: 8px; }
    .badge-success { background: #E8F5E9; color: #2E7D32; }
    .badge-error { background: #FFEBEE; color: #C62828; }
    .badge-warn { background: #FFF3E0; color: #E65100; }
    .ticket-card {
        padding: 12px;
        border: 1px solid #E0E0E0;
        border-radius: 8px;
        background: #FAFAFA;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=60)
def load_airlines():
    """读 15 航司配置 (60s 缓存,新增航司重启才生效)"""
    return list_airlines()


# 初始化 session state
for key, default in {
    "last_result": None,
    "last_airline": None,
    "last_form_data": None,
    "last_tickets": [],
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# 顶部 Header
st.markdown("""
<div class="main-header">
    <h1>🎫 客票验真平台</h1>
    <p>多航司客票验真 · 凭证生成</p>
</div>
""", unsafe_allow_html=True)

airlines = load_airlines()
if not airlines:
    st.error("未找到任何航司配置,检查 airlines/__init__.py 的 REGISTRY")
    st.stop()


# ============================================
# 侧栏:仅航司选择
# ============================================

# 访问方式 -> 颜色 (业务标注)
ACCESS_STYLES = {
    "内网网关": ("#FF9800", "#FFF3E0"),
    "需登录": ("#9C27B0", "#F3E5F5"),
    "需登录态": ("#9C27B0", "#F3E5F5"),
    "公网 API": ("#2196F3", "#E3F2FD"),
}

with st.sidebar:
    st.markdown("### ✈️ 航司")
    code_to_name = {a["code"]: a for a in airlines}
    selected_code = st.radio(
        "航司列表",
        options=list(code_to_name.keys()),
        format_func=lambda c: f"{code_to_name[c]['name']} ({c.upper()})",
        label_visibility="collapsed",
    )
    selected = code_to_name[selected_code]
    acc = selected.get("access_type", "公网 API")
    fg, bg = ACCESS_STYLES.get(acc, ("#666", "#F5F5F5"))
    st.markdown(
        f'<span class="access-tag" style="background:{bg};color:{fg};">● {acc}</span> '
        f'{len(selected["form_fields"])} 个字段',
        unsafe_allow_html=True,
    )
    st.divider()
    st.caption(f"共 {len(airlines)} 个航司")


# ============================================
# 主区
# ============================================

# 卡片 1: 查询表单
with st.container(border=True):
    acc = selected.get("access_type", "公网 API")
    fg, bg = ACCESS_STYLES.get(acc, ("#666", "#F5F5F5"))
    verify_url = selected.get("verify_url", "")

    title_html = (
        f'<span class="access-tag" style="background:{bg};color:{fg};">● {acc}</span> '
        f'代码 `{selected["code"].upper()}`'
    )
    if verify_url:
        title_md = f"#### 📋 {selected['name']}  \n{title_html}"
    else:
        title_md = f"#### 📋 {selected['name']}  \n{title_html}"
    st.markdown(title_md, unsafe_allow_html=True)

    if verify_url:
        st.link_button(
            "🌐 前往官网验真页面",
            verify_url,
            use_container_width=False,
        )

    form_data = {}
    ncols = 2 if len(selected["form_fields"]) >= 4 else 1
    cols = st.columns(ncols)
    for idx, field in enumerate(selected["form_fields"]):
        with cols[idx % ncols]:
            label = f"{field['label']}{' *' if field['required'] else ''}"
            ph = field.get("placeholder", "")
            default = field.get("default", "")
            unique_key = f"f_{field['name']}_{selected['code']}"
            if field["field_type"] == "date":
                form_data[field["name"]] = st.text_input(label, placeholder=ph or "YYYY-MM-DD", key=unique_key)
            else:
                form_data[field["name"]] = st.text_input(label, placeholder=ph, value=default, key=unique_key)

    st.divider()
    btn1, btn2, btn3 = st.columns([1, 1, 4])
    with btn1:
        submitted = st.button("🔍 查询", type="primary", use_container_width=True)
    with btn2:
        if st.button("🗑️ 清空", use_container_width=True, key="clear_form"):
            for k in ["last_result", "last_airline", "last_form_data", "last_tickets"]:
                st.session_state[k] = None if k != "last_tickets" else []
            st.rerun()


# 处理查询提交 (直接调 adapter,不绕 HTTP)
if submitted:
    with st.spinner(f"正在查询 {selected['name']}..."):
        adapter = get_adapter(selected["code"])
        if not adapter:
            result = {"success": False, "error": f"航司 {selected['code']} 不存在"}
        else:
            try:
                result = adapter.query(form_data)
            except Exception as e:
                import traceback
                result = {
                    "success": False,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                }

    st.session_state.last_result = result
    st.session_state.last_airline = selected["code"]
    st.session_state.last_form_data = form_data
    st.session_state.last_tickets = []


# 卡片 2: 查询结果
last = st.session_state.last_result
last_airline = st.session_state.last_airline
if last and last_airline == selected["code"]:
    with st.container(border=True):
        st.markdown("#### 📊 查询结果")
        if last.get("success"):
            st.markdown('<span class="badge badge-success">✅ 查询成功</span>', unsafe_allow_html=True)
            st.code(last.get("data", ""), language="text")
            # 2026-07-30: 成功也展示原始响应(用户要看全部数据,不要只展示几个字段)
            with st.expander("📦 全部数据(原始响应)"):
                st.json(last)
        else:
            st.markdown('<span class="badge badge-error">❌ 查询失败</span>', unsafe_allow_html=True)
            st.error(last.get("error", "未知错误"))
            with st.expander("查看错误详情"):
                st.code(last.get("traceback", ""), language="text")
            with st.expander("🐛 调试 - 原始响应"):
                st.json(last)

    # 卡片 3: 生成凭证 (直接调 generate_ticket_images,不绕 HTTP)
    if last.get("success"):
        flight_info = last.get("flight_info", {})
        with st.container(border=True):
            st.markdown("#### 🧾 生成凭证")

            if not flight_info:
                st.markdown('<span class="badge badge-warn">⚠️ 无法生成</span>', unsafe_allow_html=True)
                st.warning("查询结果里没有 flight_info,无法生成凭证")
            else:
                if st.button("🎫 一键生成凭证", type="primary"):
                    with st.spinner("正在生成凭证..."):
                        try:
                            payload = {
                                "airline_code": last_airline,
                                "flight_info": flight_info,
                                "flight_schedule": st.session_state.last_form_data.get("flightSchedule", ""),
                            }
                            ticket_result = generate_ticket_images(
                                payload["airline_code"],
                                payload["flight_info"],
                                payload["flight_schedule"],
                            )
                        except Exception as e:
                            ticket_result = {"success": False, "error": str(e)}

                    if ticket_result and ticket_result.get("success"):
                        st.session_state.last_tickets = ticket_result.get("tickets", [])
                        st.toast(f"✅ 已生成 {ticket_result.get('count', 0)} 张凭证", icon="🎫")
                    elif ticket_result:
                        st.error(f"❌ 生成失败: {ticket_result.get('error', '未知错误')}")
                    else:
                        st.error("❌ 无响应")

                tickets = st.session_state.last_tickets
                if tickets:
                    st.markdown(f'<span class="badge badge-success">✅ 已生成 {len(tickets)} 张</span>', unsafe_allow_html=True)
                    cols = st.columns(min(3, len(tickets)))
                    for i, ticket in enumerate(tickets):
                        with cols[i % len(cols)]:
                            st.markdown('<div class="ticket-card">', unsafe_allow_html=True)
                            st.markdown(f"**{ticket['pax_name']}**")
                            st.caption(ticket["file_name"])
                            if "png_base64" in ticket:
                                st.image(
                                    f"data:image/png;base64,{ticket['png_base64']}",
                                    use_container_width=True,
                                )
                                st.download_button(
                                    label="📥 下载凭证 PNG",
                                    data=base64.b64decode(ticket["png_base64"]),
                                    file_name=ticket["file_name"],
                                    mime="image/png",
                                    use_container_width=True,
                                    key=f"dl_{i}_{ticket['file_name']}",
                                )
                            else:
                                st.caption("(图片数据缺失)")
                            st.markdown("</div>", unsafe_allow_html=True)
