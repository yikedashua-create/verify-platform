"""航司官方验真网址 (用户手动维护)

格式: {"航司code(小写)": "https://..."}
未填的航司前端不显示"官网验真"按钮。
"""
OFFICIAL_VERIFY_URLS: dict = {
    "9c": "https://help.ch.com/Services/TravelList",
    "gq": "https://www.skyexpress.gr/en",
    "f9": "https://www.flyfrontier.com/travel/my-trips/manage-trip/",
    "ij": "https://jp.ch.com/Service/ancillary",
    "mm": "https://manage.flypeach.com/cn/manage/retrieve-booking?_gl=1*xlsn6v*_gcl_au*MTQ5NzkzNTAzMC4xNzM3NTM5MDQ1",
    "sl": "https://www.bookcabin.com/manage-bookings",
    "fr": "https://www.ryanair.com/cn/zh/lp/check-in",
    "vj": "https://www.vietjetair.com.cn/zh-CN/my/search-booking",
    "fy": "https://www.fireflyz.com.my/my/en/home.html",
    "aq": "https://www.9air.com/zh-CN/ticketValidate",
    "5j": "https://www.cebupacificair.com/zh-CN/manage-booking",
    "dd": "https://booking.nokair.com/zh/manage",
    "od": "https://www.bookcabin.com/manage-bookings",
    "lj": "https://www.jinair.com/booking/index",
    # 剩 HX / MF 还没填
    # "hx": "https://...",
    # "mf": "https://...",
}
