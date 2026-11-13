"""Render a resume variant to a simple HTML page (print it to PDF from the browser).

Fails closed: an unknown fact, an unverified fact, or a banned phrase stops the render with a
message naming what is wrong. allow_unverified=True renders unverified facts with a visible
[verify] tag, for drafts the owner reads, never for something she sends.
"""
from __future__ import annotations

from html import escape
from typing import List

from .facts import FactError, lint

STYLE = ("body{font:11pt/1.35 Arial,sans-serif;max-width:780px;margin:24px auto;color:#111}"
         "h1{font-size:20pt;margin:0}h2{font-size:11pt;border-bottom:1px solid #444;margin:14px 0 4px;text-transform:uppercase}"
         ".c{color:#444;font-size:9.5pt}.t{display:flex;justify-content:space-between;font-weight:bold}"
         ".m{font-style:italic;color:#444;font-size:9.5pt}ul{margin:2px 0 6px 18px;padding:0}.v{color:#b00;font-weight:bold}")


def _text(facts: dict, fid: str, allow_unverified: bool, problems: List[str]) -> str:
    fact = facts[fid]
    for reason in lint(fact["text"]):
        problems.append(f"{fid}: {reason}")
    if not fact.get("verified", False):
        if not allow_unverified:
            problems.append(f"{fid}: not verified yet ({fact['source']})")
        return escape(fact["text"]) + ' <span class="v">[verify]</span>'
    return escape(fact["text"])


def render_resume(data: dict, variant: str, allow_unverified: bool = False) -> str:
    if variant not in data["variants"]:
        raise FactError(f"there is no resume variant called '{variant}'")
    v, facts, problems = data["variants"][variant], data["facts"], []
    t = lambda fid: _text(facts, fid, allow_unverified, problems)
    person = data["person"]
    out = [f"<h1>{escape(person['name'])}</h1>", f'<div class="c">{escape(person.get("headline", ""))}</div>',
           '<div class="c">' + " | ".join(escape(c) for c in person.get("contact", [])) + "</div>"]
    if v.get("summary"):
        out += ["<h2>Summary</h2>", f"<p>{t(v['summary'])}</p>"]
    if v.get("skills"):
        out.append("<h2>Technical skills</h2>")
        for fid in v["skills"]:
            label = escape(facts[fid].get("group", ""))
            out.append(f"<div><b>{label + ': ' if label else ''}</b>{t(fid)}</div>")
    if v.get("projects"):
        out.append("<h2>Projects</h2>")
        for proj in v["projects"]:
            p = data["projects"][proj["id"]]
            out.append(f'<div class="t"><span>{escape(p["title"])}</span></div><div class="m">{escape(p.get("meta", ""))}</div><ul>')
            out += [f"<li>{t(fid)}</li>" for fid in proj.get("bullets", [])]
            out.append("</ul>")
    if v.get("education"):
        out.append("<h2>Education</h2>")
        out += [f"<div>{t(fid)}</div>" for fid in v["education"]]
    if v.get("extras"):
        out.append("<h2>Additional</h2>")
        out += [f"<div>{t(fid)}</div>" for fid in v["extras"]]
    if problems:
        raise FactError("; ".join(problems))
    body = "\n".join(out)
    return f'<!doctype html><html><head><meta charset="utf-8"><title>{escape(person["name"])} - {escape(variant)}</title><style>{STYLE}</style></head><body>\n{body}\n</body></html>'


def check_all(data: dict, allow_unverified: bool = False) -> dict:
    """Try every variant. Returns {variant: None if fine else the problem text}."""
    result = {}
    for name in data["variants"]:
        try:
            render_resume(data, name, allow_unverified=allow_unverified)
            result[name] = None
        except FactError as exc:
            result[name] = str(exc)
    return result
