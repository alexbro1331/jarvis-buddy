"""Detect whether another app (YouTube F11, VLC, games...) is covering the screen."""

from __future__ import annotations

import sys


def foreground_is_fullscreen(own_pids: set[int] | None = None) -> bool:
    if sys.platform == "win32":
        return _windows_fullscreen()
    return False  # Linux/macOS: not implemented, character stays visible


def _windows_fullscreen() -> bool:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False

    # Ignore the desktop / taskbar shell windows.
    cls = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, cls, 64)
    if cls.value in {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}:
        return False

    # Ignore our own window.
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    import os

    if pid.value == os.getpid():
        return False

    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    MONITOR_DEFAULTTONEAREST = 2
    monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return False

    m = info.rcMonitor
    # A fullscreen window covers the whole monitor, including the taskbar area.
    return (
        rect.left <= m.left
        and rect.top <= m.top
        and rect.right >= m.right
        and rect.bottom >= m.bottom
    )
