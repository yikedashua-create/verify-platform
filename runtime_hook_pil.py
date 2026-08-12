# PyInstaller runtime hook
# 2026-08-10: Pillow 10+ 把 PIL/__init__.py 做成 lazy 加载,
#   PyInstaller 6.20 静态扫时找不到 PIL 顶层模块,
#   PYZ 里有 PIL.Image 等子模块但没 PIL/__init__.py,
#   运行时 import PIL 抛 ModuleNotFoundError: No module named 'PIL'
# 修法: 在 exe 启动时比 user code 先 import PIL,
#   触发 lazy loader,让 PIL.__init__ 进 sys.modules
import PIL  # noqa: F401
