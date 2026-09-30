"""Wires everything together: character, voice, commands, tray, fullscreen auto-hide."""

from __future__ import annotations

import argparse
import sys
import threading
import urllib.parse
import webbrowser

from PyQt6.QtCore import QLockFile, QObject, QPoint, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMenu, QMessageBox, QSystemTrayIcon

from . import autostart, brain, commands
from .character import IDLE, LISTENING, SPEAKING, THINKING, Bubble, Character
from .config import Config, config_dir
from .fullscreen import foreground_is_fullscreen
from .voice import Listener, Speaker


class _Thinker(QObject):
    """Turns what the user said into an action + spoken reply, off the UI thread.

    Short, simple commands ("open youtube") are handled instantly by the local parser.
    Everything else goes to Claude (if an API key is set); without one, Buddy falls back
    to a Google search instead of just saying it didn't understand.
    """

    done = pyqtSignal(str, bool)  # reply text, quit after speaking?
    timer_requested = pyqtSignal(float, str)

    SIMPLE_WORDS = 6  # longer sentences are conversation, not commands

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.brain: brain.Brain | None = None

    @property
    def smart(self) -> bool:
        return brain.available(self.cfg)

    def reload(self) -> None:
        """Call after the API key or model changed."""
        self.brain = None

    def think(self, text: str) -> None:
        threading.Thread(target=self._run, args=(text,), daemon=True).start()

    def _run(self, text: str) -> None:
        try:
            if self.smart and self.brain is None:
                self.brain = brain.Brain(self.cfg, on_timer=self.timer_requested.emit)
            action = None
            if self.brain is None or len(text.split()) <= self.SIMPLE_WORDS:
                action = commands.parse(text)
                if action.kind == "unknown":
                    action = None
            if action is not None:
                self.done.emit(commands.execute(action, self.cfg), action.kind == "quit")
            elif self.brain is not None:
                self.done.emit(self.brain.ask(text), False)
            else:
                webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(text))
                self.done.emit(
                    "ये मुझे नहीं आता, इसलिए Google पे ढूँढ रहा हूँ। "
                    "Smart जवाब चाहिए तो menu से free API key जोड़ दो।",
                    False,
                )
        except Exception as e:  # never let a bad command kill the assistant
            self.done.emit(f"कुछ गड़बड़ हो गई: {e}", False)


class BuddyApp:
    def __init__(self, app: QApplication, cfg: Config):
        self.app, self.cfg = app, cfg
        self.character = Character(cfg["size"])
        self.bubble = Bubble()
        self.listener = Listener(cfg["language"], cfg)
        self.speaker = Speaker(cfg["speak_replies"], cfg["voice_gender"])
        self.thinker = _Thinker(cfg)
        self.user_hidden = False
        self.auto_hidden = False
        self._quit_after_speech = False

        self.character.tapped.connect(self.start_listening)
        self.character.moved.connect(self._remember_position)
        self.character.context_requested.connect(self._show_menu)
        self.listener.heard.connect(self._on_heard)
        self.listener.failed.connect(self._on_failed)
        self.thinker.done.connect(self._on_reply)
        self.thinker.timer_requested.connect(self._on_timer)
        self.speaker.started.connect(lambda: self.character.set_state(SPEAKING))
        self.speaker.finished.connect(self._on_speech_done)
        self.speaker.degraded.connect(lambda msg: self.bubble.show_text(msg, self.character, 10))

        self._place_initial()
        self._setup_tray()
        self.character.show()

        self._fs_timer = QTimer()
        self._fs_timer.timeout.connect(self._check_fullscreen)
        self._fs_timer.start(1000)

        QTimer.singleShot(600, lambda: self.say(f"नमस्ते {cfg['user_name']}! मैं {cfg['name']} हूँ। मुझे tap करो और बोलो!"))
        if not self.thinker.smart and not cfg["asked_key"]:
            QTimer.singleShot(4500, self._first_run_key_prompt)

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

    def _on_reply(self, reply: str, quit_after: bool) -> None:
        self._quit_after_speech = quit_after
        self.say(reply, 6)

    def _on_timer(self, minutes: float, label: str) -> None:
        QTimer.singleShot(
            int(minutes * 60_000),
            lambda: self.say(f"{self.cfg['user_name']}, याद दिलाना था: {label}", 12),
        )

    # ------------------------------------------------------------ AI keys
    KEY_CHOICES = {
        "Gemini (free) - AI brain": ("gemini", "gemini_api_key", "https://aistudio.google.com/apikey"),
        "Groq (free) - AI brain + best speech recognition": ("groq", "groq_api_key", "https://console.groq.com/keys"),
        "Claude (paid, optional)": ("claude", "anthropic_api_key", "https://console.anthropic.com/settings/keys"),
    }

    def _first_run_key_prompt(self) -> None:
        self.cfg["asked_key"] = True
        self.cfg.save()
        self.say("असली AI बनने के लिए मुझे एक free API key चाहिए। Gemini और Groq दोनों free हैं, अभी जोड़ लो।", 9)
        self.setup_keys()

    def setup_keys(self) -> None:
        """Pick a service, optionally open its free-key page, paste the key."""
        title = f"{self.cfg['name']} - AI keys"
        labels = list(self.KEY_CHOICES)
        choice, ok = QInputDialog.getItem(
            None, title,
            "Kaunsi service ki key daalni hai?\n\n"
            "Gemini aur Groq dono FREE hain (credit card nahi chahiye).\n"
            "Best setup: dono, taaki ek ki limit khatam ho to doosri kaam kare.",
            labels, 1, False,
        )
        if not ok:
            return
        name, field, url = self.KEY_CHOICES[choice]
        if QMessageBox.question(None, title, f"Key banane ka page browser mein kholun?\n{url}") == QMessageBox.StandardButton.Yes:
            webbrowser.open(url)
        key, ok = QInputDialog.getText(None, title, f"{choice}\nKey yahan paste karo:", QLineEdit.EchoMode.Password)
        if ok and key.strip():
            self.cfg[field] = key.strip()
            self.cfg.save()
            self.thinker.reload()
            extra = " Groq की key से मेरी सुनने की क्षमता भी बेहतर हो गई।" if name == "groq" else ""
            self.say("बढ़िया! अब मैं smart हो गया, कुछ भी पूछो।" + extra, 6)

    def key_status(self) -> str:
        have = [label for label, key in (("Gemini", "gemini_api_key"), ("Groq", "groq_api_key"), ("Claude", "anthropic_api_key")) if self.cfg[key]]
        if self.cfg["use_ollama"]:
            have.append("Ollama")
        return ", ".join(have) if have else "none"

    def _toggle_ollama(self, on: bool) -> None:
        self.cfg["use_ollama"] = on
        self.cfg.save()
        self.thinker.reload()
        self.bubble.show_text("Local AI chalu. Ollama install karke `ollama pull qwen3:8b` chalana hoga." if on else "Local AI band.", self.character, 6)

    def _set_stt(self, engine: str) -> None:
        self.cfg["stt_engine"] = engine
        self.cfg.save()
        self.bubble.show_text(f"Speech recognition: {engine}", self.character, 3)

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

        menu.addAction(f"🔑 AI keys… ({self.key_status()})", self.setup_keys)

        stt = menu.addMenu("👂 Speech recognition")
        for label, engine in (
            ("Auto (Groq if key, else Google)", "auto"),
            ("Groq Whisper (free, best for Hinglish)", "groq"),
            ("On this PC (faster-whisper, offline)", "local"),
            ("Google (basic)", "google"),
        ):
            act = QAction(label, stt, checkable=True)
            act.setChecked(self.cfg["stt_engine"] == engine)
            act.triggered.connect(lambda _=False, e=engine: self._set_stt(e))
            stt.addAction(act)

        ollama = QAction("🧠 Local AI (Ollama, offline)", menu, checkable=True)
        ollama.setChecked(self.cfg["use_ollama"])
        ollama.toggled.connect(self._toggle_ollama)
        menu.addAction(ollama)

        voice = menu.addMenu("🎙 Voice")
        for label, gender in (("Male", "male"), ("Female", "female")):
            act = QAction(label, voice, checkable=True)
            act.setChecked(self.cfg["voice_gender"] == gender)
            act.triggered.connect(lambda _=False, g=gender: self._set_voice(g))
            voice.addAction(act)

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

    def _set_voice(self, gender: str) -> None:
        self.cfg["voice_gender"] = gender
        self.speaker.gender = gender
        self.cfg.save()
        self.say("ये मेरी नई आवाज़ है। कैसी लगी?", 4)

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
    ap.add_argument("--make-avatar", metavar="PHOTO", help="build the cartoon character from your photo (runs locally)")
    ap.add_argument("--say", metavar="TEXT", help="run a typed command without the GUI (for testing)")
    args = ap.parse_args(argv)

    cfg = Config()
    if args.install_autostart:
        print(autostart.install())
        return 0
    if args.uninstall_autostart:
        print(autostart.uninstall())
        return 0
    if args.make_avatar:
        from .avatar import make_head

        print("Saved", make_head(args.make_avatar))
        print("Restart Buddy to see your new character.")
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
