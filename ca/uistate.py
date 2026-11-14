"""What the calendar page remembers, kept in the bot's database instead of one browser.

The page stores small text values under keys (the same ones your original page used in the browser):
dsa-done (ticks), pomo-log, pomo-cats, notes, misc-<date>, dsa-photo-<date>, and so on.
Study tasks carry the page's own tick key in their metadata, so ticks made on the page and 'done' said to
the bot stay in step both ways.
"""
from __future__ import annotations

import json
import re
from typing import Dict, Iterable, Optional

KEY = re.compile(r"^[A-Za-z0-9_.:\-]{1,80}$")
MAX_VALUE = 3_000_000                 # a day photo is a few hundred KB; this stops runaway posts


def get(conn, key: str, default: Optional[str] = None) -> Optional[str]:
    row = conn.execute("SELECT value FROM ui_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def put(conn, key: str, value: str) -> bool:
    if not KEY.match(key) or not isinstance(value, str) or len(value) > MAX_VALUE:
        return False
    conn.execute("INSERT INTO ui_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, value))
    conn.commit()
    return True


def delete(conn, key: str) -> bool:
    if not KEY.match(key):
        return False
    conn.execute("DELETE FROM ui_state WHERE key = ?", (key,))
    conn.commit()
    return True


def snapshot(conn) -> Dict[str, str]:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM ui_state")}


def import_dump(conn, dump: Dict[str, str]) -> int:
    """Load a browser-storage dump ({key: text}) such as one copied from your old page. Returns keys stored."""
    n = 0
    for key, value in dump.items():
        if isinstance(value, str) and put(conn, key, value):
            n += 1
    return n


def done_map(conn) -> dict:
    try:
        data = json.loads(get(conn, "dsa-done", "") or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _task_key(meta: str) -> str:
    try:
        return str(json.loads(meta).get("key", "")) if meta else ""
    except ValueError:
        return ""


def sync_tasks_from_state(conn) -> int:
    """Make study tasks agree with the page's ticks. Returns how many tasks changed."""
    done = done_map(conn)
    changed = 0
    for t in conn.execute("SELECT id, status, meta FROM tasks WHERE source = 'plan' AND meta != ''").fetchall():
        key = _task_key(t["meta"])
        if not key or t["status"] in ("skipped", "moved"):
            continue
        want = "done" if done.get(key) else "todo"
        if t["status"] != want:
            conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (want, t["id"]))
            changed += 1
    if changed:
        conn.commit()
    return changed


def mirror_tasks_to_state(conn, task_ids: Iterable[int]) -> None:
    """After the bot changes tasks (done, undo), write the same ticks into the page's state."""
    done = done_map(conn)
    touched = False
    for tid in task_ids:
        t = conn.execute("SELECT status, meta, source FROM tasks WHERE id = ?", (tid,)).fetchone()
        if t is None or t["source"] != "plan":
            continue
        key = _task_key(t["meta"])
        if not key:
            continue
        if t["status"] == "done" and not done.get(key):
            done[key] = 1
            touched = True
        elif t["status"] == "todo" and done.get(key):
            del done[key]
            touched = True
    if touched:
        put(conn, "dsa-done", json.dumps(done))


def export_state(conn, path) -> int:
    """Write everything the page remembers to a JSON file (your private notes repo carries it to a new server)."""
    from pathlib import Path
    data = snapshot(conn)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"ui_state": data}, ensure_ascii=False), encoding="utf-8")
    return len(data)


def import_export_file(conn, path) -> int:
    """Load a file written by export_state. Only used to start a fresh database, never to overwrite one."""
    from pathlib import Path
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8")).get("ui_state", {})
    except (OSError, ValueError, AttributeError):
        return 0
    return import_dump(conn, data) if isinstance(data, dict) else 0
