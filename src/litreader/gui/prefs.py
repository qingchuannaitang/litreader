"""GUI preferences (appearance, notifications, avatar) in <app data dir>/gui/prefs.json. Never holds a key."""
from __future__ import annotations

import json
from pathlib import Path

DEFAULTS = {"appearance": "system", "notify": True, "notify_decision": True, "notify_done": True,
            "notify_error": True, "avatar": "default",
            # G8-9/10: update check + feedback (urls empty = built-in placeholders)
            "auto_update": True, "last_update_check": "", "skipped_version": "", "remind_after": "",
            "update_urls": [], "feedback_url": "", "qq_group": ""}


class Prefs:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir) / "gui"
        self.path = self.dir / "prefs.json"
        self.d = dict(DEFAULTS)
        try:
            self.d.update({k: v for k, v in json.loads(self.path.read_text("utf-8")).items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass

    @property
    def avatar_path(self) -> Path:
        return self.dir / "avatar.png"

    def get(self, k):
        return self.d.get(k, DEFAULTS.get(k))

    def set(self, k, v) -> None:
        if k not in DEFAULTS:
            raise KeyError(k)
        self.d[k] = v
        self.save()

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.d, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self.path)
