"""Start Buddy automatically at login (Windows registry / Linux autostart)."""

from __future__ import annotations

import sys
from pathlib import Path

APP_KEY = "JarvisBuddy"


def _launcher() -> tuple[str, str]:
    """Return (python executable, launcher script) for the autostart entry."""
    exe = Path(sys.executable)
    if sys.platform == "win32":
        # pythonw.exe runs without a console window.
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.exists():
            exe = pythonw
    script = Path(__file__).resolve().parent.parent / "run_buddy.pyw"
    return str(exe), str(script)


def install() -> str:
    exe, script = _launcher()
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, APP_KEY, 0, winreg.REG_SZ, f'"{exe}" "{script}"')
        return "Autostart enabled (Windows startup)."
    if sys.platform.startswith("linux"):
        d = Path.home() / ".config" / "autostart"
        d.mkdir(parents=True, exist_ok=True)
        (d / "jarvis-buddy.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=Jarvis Buddy\n"
            f'Exec="{exe}" "{script}"\nX-GNOME-Autostart-enabled=true\n'
        )
        return "Autostart enabled (~/.config/autostart)."
    return "Autostart is not supported on this OS."


def uninstall() -> str:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, APP_KEY)
        except FileNotFoundError:
            pass
        return "Autostart disabled."
    f = Path.home() / ".config" / "autostart" / "jarvis-buddy.desktop"
    if f.exists():
        f.unlink()
    return "Autostart disabled."


def is_installed() -> bool:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
            ) as key:
                winreg.QueryValueEx(key, APP_KEY)
            return True
        except FileNotFoundError:
            return False
    return (Path.home() / ".config" / "autostart" / "jarvis-buddy.desktop").exists()
