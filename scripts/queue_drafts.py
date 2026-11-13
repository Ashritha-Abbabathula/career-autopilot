"""Queue up to N professor email drafts for your yes/skip/edit.

    python scripts/queue_drafts.py [N]

Uses targets you have marked status 'verified' in tracker/outreach_targets.csv and the verified
facts file. Nothing is sent: each draft appears in your Telegram inbox.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ca import db, facts, outreach  # noqa: E402
from ca.config import load_config  # noqa: E402


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    cfg = load_config()
    private = Path(cfg.private_dir)
    conn = db.connect(cfg.db_path)
    db.init_schema(conn)
    data = facts.load(private / "facts" / "facts.json")
    targets = outreach.select_targets(private / "tracker" / "outreach_targets.csv", n)
    if not targets:
        print("No targets marked 'verified' yet. Check a professor's page, then set status to verified in outreach_targets.csv.")
        return
    for t in targets:
        try:
            print(f"queued #{outreach.queue_draft(conn, t, data)} for {t['name']}")
        except Exception as exc:
            print(f"skipped {t.get('name', '?')}: {exc}")


if __name__ == "__main__":
    main()
