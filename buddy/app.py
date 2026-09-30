"""Wires everything together: character, voice, commands, tray, fullscreen auto-hide."""

from __future__ import annotations

import argparse
import sys
import threading

from PyQt6.QtCore import QLockFile, QObject, QPoint, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import autostart, brain, commands
from .character import IDLE, LISTENING, SPEAKING, THINKING, Bubble, Character
from .config import Config, config_dir
from .fullscreen import foreground_is_fullscreen
from .voice import Listener, Speaker


class _Thinker(QObject):
    """Resolves text -> Action off the UI thread (the Claude fallback is a network call)."""

    done = pyqtSignal(object)

    def __init__(self, model: str):
        super().__init__()
        self.model = model

    def think(self, text: str) -> None:
        threading.Thread(target=self._run, args=(text,), daemon=True).start()

    def _run(self, text: str) -> None:
        action = commands.parse(text)
        if action.kind == "unknown":
            action = brain.ask(text, self.model) or action
        self.done.emit(action)


class BuddyApp:
    def __init__(self, app: QApplication, cfg: Config):
        self.app, self.cfg = app, cfg
        self.character = Character(cfg["size"])
        self.bubble = Bubble()
        self.listener = Listener(cfg["language"])
        self.speaker = Speaker(cfg["speak_replies"])
        self.thinker = _Thinker(cfg["claude_model"])
        self.user_hidden = False
        self.auto_hidden = False
        self._quit_after_speech = False

        self.character.tapped.connect(self.start_listening)
        self.character.moved.connect(self._remember_position)
        self.character.context_requested.connect(self._show_menu)
        self.listener.heard.connect(self._on_heard)
        self.listener.failed.connect(self._on_failed)
        self.thinker.done.connect(self._on_action)
        self.speaker.started.connect(lambda: self.character.set_state(SPEAKING))
        self.speaker.finished.connect(self._on_speech_done)

        self._place_initial()
        self._setup_tray()
        self.character.show()

        self._fs_timer = QTimer()
        self._fs_timer.timeout.connect(self._check_fullscreen)
        self._fs_timer.start(1000)

        QTimer.singleShot(600, lambda: self.say(f"Namaste Chandan! Main {cfg['name']} hoon. Mujhe tap karo aur bolo!"))

    # ------------------------------------------------------------ positioning
    def _place_initial(self) -> None:
        pos = self.cfg["pos"]
        screen = self.app.primaryScreen().availableGeometry()
        if pos and screen.adjusted(-200, -200, 200, 200).contains(QPoint(*pos)):
            self.character.move(*pos)
        else:
            s = self.character.width()
            self.character.move(screen.right() - s - 20, screen.bottom() - s - 10)

    def _remember_position(self, x: int, y: int) -> None:
        self.cfg["pos"] = [x, y]
        self.cfg.save()

    # ------------------------------------------------------- fullscreen hiding
    def _check_fullscreen(self) -> None:
        if self.user_hidden:
            return
        full = foreground_is_fullscreen()
        if full and not self.auto_hidden:
            self.auto_hidden = True
            self.character.hide()
            self.bubble.hide()
        elif not full and self.auto_hidden:
            self.auto_hidden = False
            self.character.show()

    # --------------------------------------------------------------- talking
    def say(self, text: str, seconds: float = 4.0) -> None:
        self.bubble.show_text(text, self.character, seconds)
        self.speaker.say(text)

    def start_listening(self) -> None:
        if self.listener.busy:
            return
        self.character.set_state(LISTENING)
        self.bubble.show_text("Boliye, sun raha hoon...", self.character, 8)
        self.listener.listen()

    def _on_failed(self, msg: str) -> None:
        self.character.set_state(IDLE)
        self.bubble.show_text(msg, self.character, 3)

    def _on_heard(self, text: str) -> None:
        self.character.set_state(THINKING)
        self.bubble.show_text(f"“{text}”", self.character, 3)
        self.thinker.think(text)

    def _on_action(self, action: commands.Action) -> None:
        try:
            reply = commands.execute(action, self.cfg)
        except Exception as e:  # never let a bad command kill the assistant
            reply = f"Kuch gadbad ho gayi: {e}"
        self._quit_after_speech = action.kind == "quit"
        self.say(reply)

    def _on_speech_done(self) -> None:
        self.character.set_state(IDLE)
        if self._quit_after_speech:
            self.quit()

    # ------------------------------------------------------------- tray/menu
    def _setup_tray(self) -> None:
        pix = self.character.grab().scaled(64, 64)
        self.tray = QSystemTrayIcon(QIcon(pix), self.app)
        self.tray.setToolTip(self.cfg["name"])
        self.tray.setContextMenu(self._build_menu())
        self.tray.activated.connect(
            lambda reason: self.toggle_visible() if reason == QSystemTrayIcon.ActivationReason.Trigger else None
        )
        self.tray.show()

    def _build_menu(self) -> QMenu:
        menu = QMenu()
        menu.addAction("🎤 Listen", self.start_listening)
        menu.addAction("👀 Show / Hide", self.toggle_visible)

        speak = QAction("🔊 Speak replies", menu, checkable=True)
        speak.setChecked(self.cfg["speak_replies"])
        speak.toggled.connect(self._toggle_speak)
        menu.addAction(speak)

        lang = menu.addMenu("🌐 Language")
        for label, code in (("English (India)", "en-IN"), ("Hindi", "hi-IN"), ("English (US)", "en-US")):
            act = QAction(label, lang, checkable=True)
            act.setChecked(self.cfg["language"] == code)
            act.triggered.connect(lambda _=False, c=code: self._set_language(c))
            lang.addAction(act)

        auto = QAction("🚀 Start with computer", menu, checkable=True)
        auto.setChecked(autostart.is_installed())
        auto.toggled.connect(self._toggle_autostart)
        menu.addAction(auto)

        menu.addSeparator()
        menu.addAction("❌ Quit", self.quit)
        self._menu = menu  # keep a reference
        return menu

    def _show_menu(self, global_pos) -> None:
        self._build_menu().exec(global_pos)

    def toggle_visible(self) -> None:
        self.user_hidden = not self.user_hidden
        self.auto_hidden = False
        if self.user_hidden:
            self.character.hide()
            self.bubble.hide()
        else:
            self.character.show()

    def _toggle_speak(self, on: bool) -> None:
        self.cfg["speak_replies"] = on
        self.speaker.enabled = on
        self.cfg.save()

    def _set_language(self, code: str) -> None:
        self.cfg["language"] = code
        self.listener.language = code
        self.cfg.save()

    def _toggle_autostart(self, on: bool) -> None:
        msg = autostart.install() if on else autostart.uninstall()
        self.bubble.show_text(msg, self.character, 3)

    def quit(self) -> None:
        self.cfg.save()
        self.tray.hide()
        self.app.quit()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="buddy", description="Always-on-top funny voice assistant")
    ap.add_argument("--install-autostart", action="store_true", help="start automatically at login")
    ap.add_argument("--uninstall-autostart", action="store_true")
    ap.add_argument("--say", metavar="TEXT", help="run a typed command without the GUI (for testing)")
    args = ap.parse_args(argv)

    cfg = Config()
    if args.install_autostart:
        print(autostart.install())
        return 0
    if args.uninstall_autostart:
        print(autostart.uninstall())
        return 0
    if args.say:
        action = commands.parse(args.say)
        print(f"{action.kind} {action.args}")
        print(commands.execute(action, cfg))
        return 0

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)

    lock = QLockFile(str(config_dir() / "buddy.lock"))
    if not lock.tryLock(100):
        print("Buddy is already running.")
        return 0

    buddy = BuddyApp(app, cfg)  # noqa: F841 (kept alive by reference)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
