"""PlateBridge for Flash Studio."""
import argparse
import sys
from pathlib import Path

# The per-user installer launches Python in isolated mode.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from plateproject import PRINTERS, PRESETS, PROJECT_CONFIG, SETTINGS, MODEL, convert_project, export_beside_source, studio_preset


def gui():
    from pocket_ui import launch
    launch(enable_windows_drop)


def enable_windows_drop(window, on_files):
    """Queue Explorer drops without calling Tk from the native callback."""
    import ctypes as c
    from ctypes import wintypes as w
    from collections import deque

    user = c.WinDLL("user32", use_last_error=True)
    shell = c.WinDLL("shell32", use_last_error=True)
    controls = c.WinDLL("comctl32", use_last_error=True)
    result_type = c.c_ssize_t
    size_type = c.c_size_t
    callback_type = c.WINFUNCTYPE(
        result_type, w.HWND, w.UINT, w.WPARAM, w.LPARAM, size_type, size_type
    )
    user.GetParent.argtypes = [w.HWND]
    user.GetParent.restype = w.HWND
    controls.SetWindowSubclass.argtypes = [w.HWND, callback_type, size_type, size_type]
    controls.SetWindowSubclass.restype = w.BOOL
    controls.RemoveWindowSubclass.argtypes = [w.HWND, callback_type, size_type]
    controls.RemoveWindowSubclass.restype = w.BOOL
    controls.DefSubclassProc.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    controls.DefSubclassProc.restype = result_type
    shell.DragAcceptFiles.argtypes = [w.HWND, w.BOOL]
    shell.DragAcceptFiles.restype = None
    shell.DragQueryFileW.argtypes = [w.HANDLE, w.UINT, w.LPWSTR, w.UINT]
    shell.DragQueryFileW.restype = w.UINT
    shell.DragFinish.argtypes = [w.HANDLE]
    shell.DragFinish.restype = None
    window.update_idletasks()
    handle = user.GetParent(window.winfo_id()) or window.winfo_id()
    drops = deque()

    @callback_type
    def receive(hwnd, message, wparam, lparam, subclass_id, _ref):
        if message == 0x0082:  # WM_NCDESTROY
            controls.RemoveWindowSubclass(hwnd, receive, subclass_id)
        if message != 0x0233:  # WM_DROPFILES
            return controls.DefSubclassProc(hwnd, message, wparam, lparam)

        paths = []
        try:
            count = shell.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
            for index in range(count):
                size = shell.DragQueryFileW(wparam, index, None, 0) + 1
                buffer = c.create_unicode_buffer(size)
                if shell.DragQueryFileW(wparam, index, buffer, size):
                    paths.append(buffer.value)
        except Exception:
            paths = []
        finally:
            shell.DragFinish(wparam)
        drops.append(paths)
        return 0

    def process_drops():
        while drops:
            on_files(drops.popleft())
        window.after(75, process_drops)

    if not controls.SetWindowSubclass(handle, receive, 1, 0):
        raise OSError("Windows drag and drop could not be initialized.")
    window._drop_callback = receive
    shell.DragAcceptFiles(handle, True)
    window.after(75, process_drops)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?")
    parser.add_argument("output", nargs="?")
    parser.add_argument("--printer", choices=PRINTERS, default=PRINTERS[0])
    options = parser.parse_args()
    if options.source and options.output:
        print(convert_project(options.source, options.output, options.printer))
    elif options.source or options.output:
        parser.error("Provide both source and output, or launch without arguments.")
    else:
        gui()
