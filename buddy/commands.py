"""Turn what the user said into an action (English / Hinglish / Hindi).

`parse()` is pure (no side effects) so it can be unit-tested; `execute()` runs it.
"""

from __future__ import annotations

import datetime as dt
import os
import random
import re
import subprocess
import sys
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

OPEN_WORDS = r"(?:open|launch|start|run|kholo|khol do|khol de|khol|chalu karo|chalao|ओपन|खोलो|खोल दो|खोल दे|खोल|चालू करो|चलाओ)"
CREATE_WORDS = r"(?:create|make|new|banao|bana do|bana de|bana|बनाओ|बना दो|बना दे|क्रिएट|मेक)"
FILLER = {
    "please", "plz", "can", "you", "could", "buddy", "jarvis", "hey", "ok", "okay",
    "the", "a", "an", "to", "kar", "karo", "do", "de", "dena", "dijiye", "na", "ki",
    "zara", "mere", "liye", "for", "me", "app", "application", "website", "site",
    "कर", "करो", "दो", "दे", "दीजिए", "ज़रा", "मेरे", "लिए", "प्लीज", "ऐप",
}

SITES = {
    "youtube": "https://www.youtube.com",
    "यूट्यूब": "https://www.youtube.com",
    "google": "https://www.google.com",
    "गूगल": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "जीमेल": "https://mail.google.com",
    "github": "https://github.com",
    "गिटहब": "https://github.com",
    "whatsapp": "https://web.whatsapp.com",
    "व्हाट्सएप": "https://web.whatsapp.com",
    "instagram": "https://www.instagram.com",
    "इंस्टाग्राम": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "फेसबुक": "https://www.facebook.com",
    "linkedin": "https://www.linkedin.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "netflix": "https://www.netflix.com",
    "spotify": "https://open.spotify.com",
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
    "maps": "https://maps.google.com",
    "amazon": "https://www.amazon.in",
    "flipkart": "https://www.flipkart.com",
    "reddit": "https://www.reddit.com",
}

# name -> {platform: command list}
APPS = {
    "notepad": {"win32": ["notepad"], "linux": ["gedit"], "darwin": ["open", "-a", "TextEdit"]},
    "calculator": {"win32": ["calc"], "linux": ["gnome-calculator"], "darwin": ["open", "-a", "Calculator"]},
    "calc": {"win32": ["calc"], "linux": ["gnome-calculator"], "darwin": ["open", "-a", "Calculator"]},
    "paint": {"win32": ["mspaint"], "linux": ["pinta"], "darwin": ["open", "-a", "Preview"]},
    "command prompt": {"win32": ["cmd"], "linux": ["x-terminal-emulator"], "darwin": ["open", "-a", "Terminal"]},
    "cmd": {"win32": ["cmd"], "linux": ["x-terminal-emulator"], "darwin": ["open", "-a", "Terminal"]},
    "terminal": {"win32": ["wt"], "linux": ["x-terminal-emulator"], "darwin": ["open", "-a", "Terminal"]},
    "file explorer": {"win32": ["explorer"], "linux": ["xdg-open", "."], "darwin": ["open", "."]},
    "explorer": {"win32": ["explorer"], "linux": ["xdg-open", "."], "darwin": ["open", "."]},
    "files": {"win32": ["explorer"], "linux": ["xdg-open", "."], "darwin": ["open", "."]},
    "chrome": {"win32": ["cmd", "/c", "start", "", "chrome"], "linux": ["google-chrome"], "darwin": ["open", "-a", "Google Chrome"]},
    "edge": {"win32": ["cmd", "/c", "start", "", "msedge"], "linux": ["microsoft-edge"], "darwin": ["open", "-a", "Microsoft Edge"]},
    "firefox": {"win32": ["cmd", "/c", "start", "", "firefox"], "linux": ["firefox"], "darwin": ["open", "-a", "Firefox"]},
    "vlc": {"win32": ["cmd", "/c", "start", "", "vlc"], "linux": ["vlc"], "darwin": ["open", "-a", "VLC"]},
    "vs code": {"win32": ["cmd", "/c", "start", "", "code"], "linux": ["code"], "darwin": ["open", "-a", "Visual Studio Code"]},
    "vscode": {"win32": ["cmd", "/c", "start", "", "code"], "linux": ["code"], "darwin": ["open", "-a", "Visual Studio Code"]},
    "word": {"win32": ["cmd", "/c", "start", "", "winword"], "linux": ["libreoffice", "--writer"], "darwin": ["open", "-a", "Microsoft Word"]},
    "excel": {"win32": ["cmd", "/c", "start", "", "excel"], "linux": ["libreoffice", "--calc"], "darwin": ["open", "-a", "Microsoft Excel"]},
    "settings": {"win32": ["cmd", "/c", "start", "", "ms-settings:"], "linux": ["gnome-control-center"], "darwin": ["open", "-a", "System Settings"]},
    "task manager": {"win32": ["taskmgr"], "linux": ["gnome-system-monitor"], "darwin": ["open", "-a", "Activity Monitor"]},
}

JOKES = [
    "Computer ने doctor को क्या बोला? मुझे virus हो गया है! Doctor बोला, मैं Windows का नहीं, इंसानों का doctor हूँ!",
    "Programmers dark mode क्यों पसंद करते हैं? क्योंकि light से bugs आते हैं!",
    "मेरा WiFi और मेरी lovelife एक जैसे हैं। दोनों में signal नहीं आता।",
    "मैंने अपने computer को बोला कि मुझे break चाहिए। अब वो मुझे सिर्फ़ Kit Kat के ads दिखा रहा है।",
    "Laptop को ठंड क्यों लग रही थी? क्योंकि उसकी Windows खुली रह गई थी!",
    "Chandan, आज code पहली बार में चल गया? किसी को बताना मत, मुझे भी नहीं पता कैसे चला!",
]


@dataclass
class Action:
    kind: str  # open_url, open_app, create_folder, search, say, volume, screenshot, lock, quit, unknown, ...
    args: dict = field(default_factory=dict)


def _norm(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[.,!?;:।]+", " ", text)
    return re.sub(r"\s+", " ", text)


def _strip_fillers(text: str) -> str:
    return " ".join(w for w in text.split() if w not in FILLER).strip()


def _folder_name(text: str) -> str | None:
    """Extract the folder name from a 'create folder ...' sentence."""
    m = re.search(r"(?:named|name|called)\s+(.+)", text)
    if m:
        return _clean_name(m.group(1))
    m = re.search(r"(.+?)\s+(?:ke naam se|ke naam ka|naam se|naam ka|के नाम से|के नाम का|नाम से)(?=\s|$)", text)
    if m:
        # the name is the last word(s) before "ke naam se", minus verbs/fillers.
        before = re.sub(CREATE_WORDS, " ", m.group(1))
        before = re.sub(r"(?<!\S)(?:folder|फोल्डर|directory)(?!\S)", " ", before)
        return _clean_name(before)
    rest = re.sub(CREATE_WORDS, " ", text)
    rest = re.sub(r"(?<!\S)(?:folder|फोल्डर|directory)(?!\S)", " ", rest)
    return _clean_name(rest)


def _clean_name(raw: str) -> str | None:
    raw = _strip_fillers(raw)
    raw = re.sub(r'[\\/:*?"<>|]', "", raw).strip()
    return raw.title() if raw else None


def parse(raw: str) -> Action:
    text = _norm(raw)
    if not text:
        return Action("unknown")

    # --- quit ---
    if re.search(r"\b(?:quit|exit|goodbye|bye|band ho ja|band ho jao)\b|बंद हो जा", text):
        return Action("quit")

    # --- folder creation ---
    if re.search(r"\b(?:folder|directory)\b|फोल्डर", text) and re.search(CREATE_WORDS, text):
        name = _folder_name(text)
        location = None
        for loc in ("desktop", "documents", "downloads"):
            if re.search(rf"\b{loc}\b", text):
                location = loc.title()
        if name:
            for loc in ("desktop", "documents", "downloads"):
                name = re.sub(rf"\b(?:in|on|inside)?\s*{loc}\b", "", name, flags=re.I).strip()
        return Action("create_folder", {"name": name, "location": location}) if name else Action(
            "say", {"text": "Folder का नाम बताओ, कौन सा नाम रखूँ?"}
        )

    # --- time / date ---
    if re.search(r"\b(?:time|samay|kitne baje|baje)\b|टाइम|समय|कितने बजे", text):
        return Action("time")
    if re.search(r"\b(?:date|today|aaj kya tarikh|tarikh)\b|तारीख", text):
        return Action("date")

    # --- joke ---
    if re.search(r"\b(?:joke|funny|hasao|chutkula)\b|जोक|चुटकुला|हंसाओ", text):
        return Action("say", {"text": random.choice(JOKES)})

    # --- volume ---
    if re.search(r"\b(?:volume|awaaz|sound)\b|आवाज़|आवाज|वॉल्यूम", text):
        if re.search(r"\b(?:up|increase|badha|badhao|zyada|louder)\b|बढ़ा", text):
            return Action("volume", {"dir": "up"})
        if re.search(r"\b(?:down|decrease|kam|ghata|lower)\b|कम|घटा", text):
            return Action("volume", {"dir": "down"})
        if re.search(r"\b(?:mute|band|off)\b|म्यूट|बंद", text):
            return Action("volume", {"dir": "mute"})
    if re.search(r"\bmute\b|म्यूट", text):
        return Action("volume", {"dir": "mute"})

    # --- screenshot / lock ---
    if re.search(r"\bscreenshot\b|स्क्रीनशॉट", text):
        return Action("screenshot")
    if re.search(r"\block\b.*\b(?:pc|laptop|computer|screen)\b|\block\b|लॉक", text):
        return Action("lock")

    # --- play on youtube ---
    m = re.search(r"\bplay\s+(.+)|(.+?)\s+(?:play kar|play karo|chala do|chalao|बजाओ|चला दो)", text)
    if m:
        query = _strip_fillers((m.group(1) or m.group(2)).replace("on youtube", "").replace("youtube par", ""))
        if query:
            return Action("open_url", {"url": "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query), "label": f"YouTube pe {query}"})

    # --- web search ---
    m = re.search(r"\b(?:search|google|look up|dhundo|dhoondo|खोजो|ढूंढो)\b\s*(?:for|about)?\s*(.+)", text)
    if m:
        query = _strip_fillers(m.group(1))
        if query:
            return Action("search", {"query": query})

    # --- open something ---
    if re.search(OPEN_WORDS, text):
        target = re.sub(OPEN_WORDS, " ", text)
        target = _strip_fillers(re.sub(r"\s+", " ", target))
        target = re.sub(r"\b(?:par|pe|में|mein)\b", " ", target).strip()
        if target:
            return _open_target(target)

    return Action("unknown", {"text": raw})


def _open_target(target: str) -> Action:
    for key, cmds in APPS.items():
        if target == key:
            return Action("open_app", {"name": key, "cmd": cmds})
    for key, url in SITES.items():
        if target == key or target == f"{key} com" or target == f"{key}.com":
            return Action("open_url", {"url": url, "label": key})
    if re.fullmatch(r"[\w.-]+\.(?:com|in|org|net|io|dev|ai|co)(?:/\S*)?", target):
        return Action("open_url", {"url": "https://" + target, "label": target})
    # partial matches ("youtube please" already stripped; "google chrome" etc.)
    for key, cmds in APPS.items():
        if key in target:
            return Action("open_app", {"name": key, "cmd": cmds})
    for key, url in SITES.items():
        if key in target.split():
            return Action("open_url", {"url": url, "label": key})
    return Action("open_app", {"name": target, "cmd": None})


# ----------------------------------------------------------------- execution


def _known_folder(name: str) -> Path:
    home = Path.home()
    # Windows often redirects Desktop/Documents into OneDrive.
    for cand in (home / name, home / "OneDrive" / name):
        if cand.exists():
            return cand
    return home


def execute(action: Action, cfg=None) -> str:
    """Run the action and return a short sentence for the character to say."""
    k, a = action.kind, action.args

    if k == "say":
        return a["text"]

    if k == "open_url":
        webbrowser.open(a["url"])
        return f"{a.get('label', 'Website')} खोल दिया!"

    if k == "search":
        webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(a["query"]))
        return f"{a['query']} search कर रहा हूँ।"

    if k == "open_app":
        return _open_app(a)

    if k == "create_folder":
        loc_name = a.get("location") or (cfg["folder_location"] if cfg else "Desktop")
        base = _known_folder(loc_name)
        path = base / a["name"]
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return f"फ़ोल्डर नहीं बन पाया: {e.strerror or e}"
        return f"{a['name']} नाम का folder {base.name} में बना दिया।"

    if k == "time":
        return "अभी " + dt.datetime.now().strftime("%I:%M %p") + " बज रहे हैं।"

    if k == "date":
        return "आज " + dt.datetime.now().strftime("%A, %d %B %Y") + " है।"

    if k == "volume":
        return _volume(a["dir"])

    if k == "screenshot":
        return _screenshot()

    if k == "lock":
        return _lock()

    if k == "quit":
        return "बाय बाय! फिर मिलते हैं।"

    return "मुझे समझ नहीं आया, दोबारा बोलो?"


def _open_app(a: dict) -> str:
    name, cmds = a["name"], a.get("cmd")
    plat = "win32" if sys.platform == "win32" else "darwin" if sys.platform == "darwin" else "linux"
    try:
        if cmds:
            subprocess.Popen(cmds[plat], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform == "win32":
            subprocess.Popen(["cmd", "/c", "start", "", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-a", name])
        else:
            subprocess.Popen([name.replace(" ", "-")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"{name} खोल रहा हूँ।"
    except (OSError, KeyError):
        webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(name))
        return f"{name} मुझे नहीं मिला, Google पे ढूँढ रहा हूँ।"


def _volume(direction: str) -> str:
    if sys.platform != "win32":
        return "Volume control अभी सिर्फ़ Windows पे चलता है।"
    import ctypes

    keys = {"up": 0xAF, "down": 0xAE, "mute": 0xAD}
    presses = 5 if direction in ("up", "down") else 1
    for _ in range(presses):
        ctypes.windll.user32.keybd_event(keys[direction], 0, 0, 0)
        ctypes.windll.user32.keybd_event(keys[direction], 0, 2, 0)
    return {"up": "आवाज़ बढ़ा दी।", "down": "आवाज़ कम कर दी।", "mute": "Mute कर दिया।"}[direction]


def _screenshot() -> str:
    try:
        from PIL import ImageGrab
    except ImportError:
        return "Screenshot के लिए Pillow install करो: pip install pillow"
    out = Path.home() / "Pictures"
    out.mkdir(exist_ok=True)
    path = out / f"buddy-{dt.datetime.now():%Y%m%d-%H%M%S}.png"
    ImageGrab.grab().save(path)
    return "Screenshot Pictures folder में save कर दिया।"


def _lock() -> str:
    if sys.platform == "win32":
        subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
        return "Screen lock कर रहा हूँ।"
    return "Lock अभी सिर्फ़ Windows पे चलता है।"
