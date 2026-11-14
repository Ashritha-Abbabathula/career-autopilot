"""Rebuild the calendar page's saved state from the PDF that the original 90-day page exports.

    python scripts/import_from_plan_pdf.py "path\\to\\90-day-plan.pdf" [--dry-run]

The PDF lists every day with [x] / [ ] for each item, the misc work you added, and the time you logged, so the
ticks, misc items and Pomodoro minutes can be rebuilt exactly. Sticky notes and photos are not in the PDF.
It checks its own totals against the summary line at the top of the PDF before saving anything.
Needs pdftotext (or the pypdf package) and the private original_schedule.json.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ca import db, uistate  # noqa: E402
from ca.config import load_config  # noqa: E402

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
SEED_FLAGS = ["seed-v1", "seed-v2", "seed-v3", "seed-v4", "mig-v2"]     # stop the page from re-adding its starter items


def pdf_text(path: str) -> str:
    try:
        return subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, check=True,
                              encoding="utf-8").stdout
    except (OSError, subprocess.CalledProcessError):
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def minutes(token: str) -> int:
    """The page writes durations as 5h, 1h30 or 40m."""
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m?)?", token.strip())
    if not m or not (m.group(1) or m.group(2)):
        return 0
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)


def parse(text: str, sched: dict) -> dict:
    done, misc, events_done, log = {}, {}, {}, {}
    year, month = None, None
    day, mode, ev_i, col_i, gate_j = None, None, 0, 0, 0
    last_misc = None
    summary = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or re.fullmatch(r"Page \d+ of \d+", line):
            continue
        if re.search(r"\d+/\d+ DSA", line):
            summary = line
            continue
        m = re.fullmatch(r"(" + "|".join(MONTHS) + r") (\d{4})", line)
        if m:
            month, year = MONTHS.index(m.group(1)) + 1, int(m.group(2))
            day = None
            continue
        m = re.match(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\d{1,2}) [A-Z][a-z]{2}\b", line)
        if m and year:
            day = f"{year}-{month:02d}-{int(m.group(2)):02d}"
            mode, ev_i, col_i, gate_j, last_misc = None, 0, 0, 0, None
            continue
        if day is None:
            continue
        mark = lambda s: s.startswith("[x]")
        if line.startswith("MISC "):
            body = line[5:].strip()
            misc.setdefault(day, []).append({"t": body[3:].strip(), "d": 1 if mark(body) else 0})
            last_misc, mode = misc[day][-1], None
        elif line.startswith("EVENT "):
            body = line[6:].strip()
            if mark(body):
                events_done[f"e{day}-{ev_i}"] = 1
            ev_i += 1
            mode, last_misc = None, None
        elif line.startswith("DSA ("):
            mode, last_misc = "dsa", None
        elif line.startswith("GATE ("):
            mode, last_misc, gate_j = "gate", None, 0
        elif line.startswith("ML/YouTube"):
            mode, last_misc = None, None
            if "[x]" in line and day in sched.get("plan", {}):
                done[f"y{sched['plan'][day]}"] = 1
        elif line.startswith("College ("):
            mode, last_misc = None, None
            mods = sched.get("cm", {}).get(day, [])
            if "[x]" in line and col_i < len(mods):
                done[f"c{mods[col_i]}"] = 1
            col_i += 1
        elif line.startswith("Time logged:"):
            mode, last_misc = None, None
            inner = re.search(r"\((.*)\)", line)
            cats = {}
            for part in (inner.group(1).split(", ") if inner else []):
                name, _, dur = part.rpartition(" ")
                if name and minutes(dur):
                    cats[name] = minutes(dur)
            if cats:
                log[day] = cats
        elif mode == "dsa" and re.match(r"\[( |x)\] \d+\.", line):
            if mark(line):
                done[re.match(r"\[x\] (\d+)\.", line).group(1)] = 1
        elif mode == "gate" and re.match(r"\[( |x)\] ", line):
            if mark(line) and day in sched.get("mp", {}):
                done[f"g{sched['mp'][day]}-{gate_j}"] = 1
            gate_j += 1
        elif last_misc is not None:
            last_misc["t"] += " " + line                       # a long misc item wrapped onto the next line
    return {"done": done, "events": events_done, "misc": misc, "log": log, "summary": summary}


def check(parsed: dict, sched: dict) -> list:
    """Compare against the totals the page printed at the top of the PDF. Returns a list of problems."""
    problems = []
    ids = {str(pid) for d in sched["DAYS"] for pid, _ in d[1]}
    dsa = sum(1 for k in parsed["done"] if k in ids)
    yt = sum(1 for k in parsed["done"] if re.fullmatch(r"y\d+", k))
    gate = sum(1 for k in parsed["done"] if re.fullmatch(r"g\d+-\d+", k))
    col = sum(1 for k in parsed["done"] if re.fullmatch(r"c\d+", k))
    m = re.search(r"(\d+)/\d+ DSA - (\d+)/\d+ GATE - (\d+)/\d+ YouTube - (\d+)/\d+ College", parsed["summary"])
    if not m:
        return ["could not read the summary line at the top of the PDF"]
    want_dsa, want_gate_days, want_yt, want_col = map(int, m.groups())
    if dsa != want_dsa:
        problems.append(f"DSA ticks {dsa} but the PDF says {want_dsa}")
    if yt != want_yt:
        problems.append(f"YouTube ticks {yt} but the PDF says {want_yt}")
    if col != want_col:
        problems.append(f"College ticks {col} but the PDF says {want_col}")
    gate_days_done = sum(1 for g, d in enumerate(sched["GD"])
                         if all(parsed["done"].get(f"g{g}-{j}") for j in range(len(d["it"]))))
    if gate_days_done != want_gate_days:
        problems.append(f"GATE days {gate_days_done} but the PDF says {want_gate_days}")
    return problems


def to_state(parsed: dict) -> dict:
    state = {"dsa-done": json.dumps({**parsed["done"], **parsed["events"]}), "pomo-log": json.dumps(parsed["log"])}
    for day, items in parsed["misc"].items():
        state[f"misc-{day}"] = json.dumps(items, ensure_ascii=False)
    for flag in SEED_FLAGS:
        state[flag] = "1"
    return state


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    cfg = load_config(env_file=str(Path(__file__).resolve().parent.parent / ".env"))
    root = Path(__file__).resolve().parent.parent
    private = Path(cfg.private_dir) if Path(cfg.private_dir).is_absolute() else (root / cfg.private_dir).resolve()
    sched = json.loads((private / "calendar" / "original_schedule.json").read_text(encoding="utf-8"))
    parsed = parse(pdf_text(args[0]), sched)
    problems = check(parsed, sched)
    print("PDF summary:", parsed["summary"])
    print(f"found: {len(parsed['done'])} ticks, {len(parsed['events'])} ticked events, "
          f"{sum(len(v) for v in parsed['misc'].values())} misc items, {len(parsed['log'])} days with logged time")
    if problems:
        print("NOT imported, totals do not match:", "; ".join(problems))
        return 1
    state = to_state(parsed)
    if "--dry-run" in sys.argv:
        print("dry run: totals match, nothing saved")
        return 0
    db_path = cfg.db_path if Path(cfg.db_path).is_absolute() else str((root / cfg.db_path).resolve())
    conn = db.connect(db_path)
    db.init_schema(conn)
    saved = uistate.import_dump(conn, state)
    changed = uistate.sync_tasks_from_state(conn)
    print(f"saved {saved} items; {changed} study tasks updated to match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
