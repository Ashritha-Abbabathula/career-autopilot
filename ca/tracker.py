"""The application tracker: one row per thing the owner might apply to or has applied to.

The CSV layout matches the owner's spreadsheet, so the same file can be opened in
Excel or Google Sheets, edited there, and imported back.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import List, Optional

FIELDS = ["organisation", "role_or_programme", "location", "source_link", "date_found", "deadline",
          "match_note", "decision", "resume_version", "date_applied", "method", "contact", "status",
          "next_action", "next_action_date", "notes"]
CSV_HEADER = ["id"] + FIELDS
DECISIONS = {"APPLY", "MAYBE", "SKIP", "WATCH", "APPLY LATER"}
# Statuses that mean the application has left her hands.
SUBMITTED = {"applied", "submitted", "interview", "offer", "rejected", "accepted", "withdrawn"}


def _clean(fields: dict) -> dict:
    out = {}
    for key, value in fields.items():
        if key not in FIELDS:
            raise ValueError(f"unknown tracker field: {key}")
        out[key] = "" if value is None else str(value).strip()
    if "decision" in out:
        d = out["decision"].upper()
        out["decision"] = d if d in DECISIONS else "MAYBE"
    if "status" in out and not out["status"]:
        out["status"] = "not started"
    return out


def add(conn, organisation: str, role_or_programme: str, **fields) -> int:
    row = _clean({"organisation": organisation, "role_or_programme": role_or_programme, **fields})
    if not row["organisation"] or not row["role_or_programme"]:
        raise ValueError("an application needs an organisation and a role or programme")
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    cur = conn.execute(f"INSERT INTO applications ({cols}) VALUES ({marks})", list(row.values()))
    conn.commit()
    return cur.lastrowid


def get(conn, app_id: int):
    return conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()


def find(conn, organisation: str, role_or_programme: str):
    return conn.execute(
        "SELECT * FROM applications WHERE lower(organisation) = lower(?) AND lower(role_or_programme) = lower(?)",
        (organisation.strip(), role_or_programme.strip())).fetchone()


_STOP = {"the", "of", "and", "for", "a", "an", "in", "at", "to", "summer", "intern", "internship", "program", "programme", "2026", "2027", "fellowship", "research"}


def _words(text: str) -> set:
    return {w for w in "".join(c.lower() if c.isalnum() else " " for c in text or "").split() if w not in _STOP and len(w) > 2}


def find_similar(conn, organisation: str, role_or_programme: str, link: str = ""):
    """An existing row that is almost certainly the same opportunity: same link, or the same organisation
    (one name contains the other, or they share a distinctive word) with overlapping role words."""
    rows = conn.execute("SELECT * FROM applications").fetchall()
    link = (link or "").strip().rstrip("/").lower()
    for r in rows:
        if link and (r["source_link"] or "").strip().rstrip("/").lower() == link:
            return r
    org, role = _words(organisation), _words(role_or_programme)
    for r in rows:
        same_org = org & _words(r["organisation"])
        same_role = role & _words(r["role_or_programme"])
        if same_org and (same_role or not role or not _words(r["role_or_programme"])):
            return r
    return None


def update(conn, app_id: int, **fields) -> None:
    if get(conn, app_id) is None:
        raise KeyError(f"no application {app_id}")
    row = _clean(fields)
    if not row:
        return
    sets = ", ".join(f"{k} = ?" for k in row)
    conn.execute(f"UPDATE applications SET {sets} WHERE id = ?", list(row.values()) + [app_id])
    conn.commit()


def mark_applied(conn, app_id: int, today: date, method: str = "") -> None:
    fields = {"status": "applied", "date_applied": today.isoformat()}
    if method:
        fields["method"] = method
    update(conn, app_id, **fields)


def list_apps(conn, status: Optional[str] = None, decision: Optional[str] = None) -> List:
    sql, args = "SELECT * FROM applications WHERE 1=1", []
    if status:
        sql += " AND lower(status) = lower(?)"
        args.append(status)
    if decision:
        sql += " AND decision = ?"
        args.append(decision.upper())
    return conn.execute(sql + " ORDER BY id", args).fetchall()


def import_csv(conn, path) -> dict:
    """Read the owner's CSV. A row that matches an existing organisation and role updates it."""
    added = updated = skipped = 0
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        for raw in csv.DictReader(fh):
            fields = {k: (raw.get(k) or "") for k in FIELDS if k in raw}
            org, role = fields.get("organisation", "").strip(), fields.get("role_or_programme", "").strip()
            if not org or not role:
                skipped += 1
                continue
            existing = find(conn, org, role)
            if existing is None:
                add(conn, **fields)
                added += 1
            else:
                update(conn, existing["id"], **fields)
                updated += 1
    return {"added": added, "updated": updated, "skipped": skipped}


def merge_csv(conn, path) -> dict:
    """Bring in rows that appeared in the CSV (the scout, or you in a spreadsheet). Existing rows keep
    what the database has; the CSV only fills fields the database left empty. Nothing is overwritten."""
    p = Path(path)
    if not p.is_file():
        return {"added": 0, "filled": 0}
    added = filled = 0
    with p.open(newline="", encoding="utf-8-sig") as fh:
        for raw in csv.DictReader(fh):
            fields = {k: (raw.get(k) or "") for k in FIELDS if k in raw}
            org, role = fields.get("organisation", "").strip(), fields.get("role_or_programme", "").strip()
            if not org or not role:
                continue
            existing = find(conn, org, role)
            if existing is None:
                add(conn, **fields)
                added += 1
                continue
            gaps = {k: v for k, v in fields.items() if v.strip() and not (existing[k] or "").strip()
                    and k not in ("status", "decision")}
            if gaps:
                update(conn, existing["id"], **gaps)
                filled += 1
    return {"added": added, "filled": filled}


def sync_csv(conn, path) -> dict:
    """Merge new CSV rows in, then write the database back out, so the file always shows the latest."""
    result = merge_csv(conn, path)
    result["written"] = export_csv(conn, path)
    return result


def export_csv(conn, path) -> int:
    rows = list_apps(conn)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADER)
        for r in rows:
            writer.writerow([r[c] for c in CSV_HEADER])
    return len(rows)


def is_submitted(row) -> bool:
    return (row["status"] or "").strip().lower() in SUBMITTED


def summary_text(conn, limit: int = 8) -> str:
    """A short, honest picture: what is applied, what is being prepared, what is waiting."""
    rows = list_apps(conn)
    if not rows:
        return "Your tracker is empty."
    applied = [r for r in rows if is_submitted(r)]
    to_apply = [r for r in rows if not is_submitted(r) and r["decision"] in ("APPLY", "APPLY LATER")]
    maybe = [r for r in rows if not is_submitted(r) and r["decision"] in ("MAYBE", "WATCH")]
    lines = [f"Applied: {len(applied)} | To apply: {len(to_apply)} | Watching: {len(maybe)}"]

    def show(title, items, extra):
        if not items:
            return
        lines.append(title)
        for r in items[:limit]:
            lines.append(f"{r['id']}. {r['organisation']}: {r['role_or_programme']}{extra(r)}")
        if len(items) > limit:
            lines.append(f"...and {len(items) - limit} more")

    show("Applied:", applied, lambda r: f" ({r['status']}" + (f", {r['date_applied']}" if r["date_applied"] else "") + ")")
    show("To apply:", to_apply, lambda r: f" (deadline {r['deadline']})" if r["deadline"] else "")
    show("Watching:", maybe, lambda r: "")
    return "\n".join(lines)
