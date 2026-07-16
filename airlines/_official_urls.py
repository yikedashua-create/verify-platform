"""航司官方验真网址 (用户手动维护)

格式: {"航司code(小写)": "https://..."}
未填的航司前端不显示"官网验真"按钮。
"""
OFFICIAL_VERIFY_URLS: dict = {
    "9c": "https://help.ch.com/Services/TravelList",
    # 后续航司 URL 继续往下加
    # "dd": "https://...",
    # "od": "https://...",
}
