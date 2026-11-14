"""Save the calendar's ticks, notes, Pomodoro log and photos into your private notes folder.

    python scripts/export_state.py

Commit and push your notes repo afterwards. A new server then starts with exactly this state (no file copying).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ca import db, uistate  # noqa: E402
from ca.config import load_config  # noqa: E402

root = Path(__file__).resolve().parent.parent
cfg = load_config(env_file=str(root / ".env"))
absolute = lambda p: Path(p) if Path(p).is_absolute() else (root / p).resolve()
conn = db.connect(str(absolute(cfg.db_path)))
db.init_schema(conn)
target = absolute(cfg.private_dir) / "calendar" / "state_export.json"
print(f"saved {uistate.export_state(conn, target)} items to {target}")
