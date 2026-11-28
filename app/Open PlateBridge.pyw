from pathlib import Path
import ctypes
import runpy
import sys

try:
    if sys.version_info < (3, 12):
        raise RuntimeError("PlateBridge needs Python 3.12 or newer with Tk support.")
    runpy.run_path(str(Path(__file__).with_name("PlateBridge.py")), run_name="__main__")
except Exception as error:
    ctypes.windll.user32.MessageBoxW(None, f"{type(error).__name__}: {error}", "PlateBridge could not start", 16)
