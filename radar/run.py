"""Skills radar: what do India-based tech postings actually ask for?

Usage (from the project folder):
    python -m radar.run --companies data/companies.txt --paste data/paste --out out

Reads public job-board APIs (Greenhouse, Lever, Ashby) for the companies you
list, adds any text you pasted yourself, counts skills, and writes a report
comparing the counts with what your resumes show.
"""
import argparse
import collections
import csv
import datetime
import os

from . import filters, skills, sources


def read_entries(path):
    with open(path, encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]


def collect(entries, paste_dir):
    postings, status = [], {}
    for entry in entries:
        got, err = sources.load_company(entry)
        status[entry] = (len(got), err)
        postings.extend(got)
    pasted = sources.load_paste_dir(paste_dir) if paste_dir else []
    return postings, pasted, status


def analyse(postings, pasted):
    """Keep India tech postings; tag level and skills. Pasted text is kept as-is."""
    rows = []
    for p in postings:
        if not (filters.in_india(p["location"]) and filters.is_tech(p["title"])):
            continue
        level = filters.level_of(p["title"])
        rows.append({**p, "level": level, "city": filters.in_target_city(p["location"]),
                     "skills": skills.find_skills(p["title"] + " " + p["text"])})
    for p in pasted:
        rows.append({**p, "level": "pasted", "city": False, "skills": skills.find_skills(p["text"])})
    return rows


def share(rows, predicate):
    sel = [r for r in rows if predicate(r)]
    counts = collections.Counter(s for r in sel for s in r["skills"])
    return len(sel), counts


def table(counts, n, top=25):
    lines = ["| Skill | Category | Postings | Share | On your resume? |", "|---|---|---|---|---|"]
    for name, c in counts.most_common(top):
        have = ("yes" if name in skills.ON_RESUME else
                "in projects, not on resume" if name in skills.IN_PROJECTS_NOT_ON_RESUME else "**no**")
        lines.append(f"| {name} | {skills.category_of(name)} | {c} | {100 * c / n:.0f}% | {have} |")
    return "\n".join(lines)


def report(rows, status, today):
    total = len(rows)
    live = {k: v for k, v in status.items() if v[1] is None}
    failed = {k: v for k, v in status.items() if v[1] is not None}
    lvl = collections.Counter(r["level"] for r in rows)
    out = [f"# Skills radar report, {today}", "",
           "**What this is:** counts of skills in public job postings (Greenhouse, Lever, Ashby APIs) "
           "for India-located tech roles, plus text you pasted. It shows what *these companies* ask for, "
           "not all hiring managers. Small samples are labelled.", "",
           f"- Companies that answered: {len(live)} of {len(status)} tried. "
           f"Postings kept (India, tech): **{total}**.",
           f"- By level (guessed from titles): " + ", ".join(f"{k} {v}" for k, v in lvl.most_common()), ""]
    for label, pred in [
        ("All India tech postings", lambda r: r["level"] != "pasted"),
        ("Entry-level and intern postings only", lambda r: r["level"] in ("intern", "entry")),
        ("Not senior (intern, entry and mid titles): closest to what you can grow into",
         lambda r: r["level"] in ("intern", "entry", "mid")),
        ("Bengaluru or Hyderabad only", lambda r: r["city"]),
        ("Text you pasted (LinkedIn posts, Reddit threads, job descriptions)", lambda r: r["level"] == "pasted"),
    ]:
        n, counts = share(rows, pred)
        out += [f"## {label} (n = {n})", ""]
        if n == 0:
            out += ["No postings in this group yet.", ""]
            continue
        if n < 15:
            out += [f"*Only {n} postings: treat percentages as a rough hint, not a finding.*", ""]
        out += [table(counts, n), ""]
        if label.startswith("All India"):
            missing = [(s, c) for s, c in counts.most_common() if s not in skills.ON_RESUME
                       and s not in skills.IN_PROJECTS_NOT_ON_RESUME][:12]
            show = [(s, c) for s, c in counts.most_common() if s in skills.IN_PROJECTS_NOT_ON_RESUME]
            out += ["**Most-asked skills missing from both resumes and projects:** "
                    + (", ".join(f"{s} ({100 * c / n:.0f}%)" for s, c in missing) or "none"), "",
                    "**You already have these in projects but they are not on the resume:** "
                    + (", ".join(f"{s} ({100 * c / n:.0f}%)" for s, c in show) or "none"), ""]
    out += ["## Sources that answered / failed", ""]
    out += [f"- OK {k}: {v[0]} postings" for k, v in live.items()]
    out += [f"- FAILED {k}: {v[1]}" for k, v in failed.items()]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--companies", default="data/companies.txt")
    ap.add_argument("--paste", default="data/paste")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    today = datetime.date.today().isoformat()
    postings, pasted, status = collect(read_entries(a.companies), a.paste)
    rows = analyse(postings, pasted)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, f"postings_{today}.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["company", "title", "location", "level", "url", "skills"])
        for r in rows:
            w.writerow([r["company"], r["title"], r["location"], r["level"], r["url"], "; ".join(sorted(r["skills"]))])
    path = os.path.join(a.out, f"skills_{today}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report(rows, status, today))
    print(f"wrote {path} ({len(rows)} postings kept)")


if __name__ == "__main__":
    main()
