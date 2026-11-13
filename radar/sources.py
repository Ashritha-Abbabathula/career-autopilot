"""Job-posting sources that publish official public job-board APIs.

Greenhouse, Lever and Ashby each offer a public JSON endpoint that companies
use to embed their own careers page. We read those, slowly, with an honest
User-Agent. We do NOT scrape LinkedIn, Indeed or Reddit.
"""
import json
import time
import urllib.error
import urllib.request

from .skills import clean_text

UA = "career-skills-radar/0.1 (personal research project, low rate)"
DELAY_SECONDS = 0.6


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def greenhouse(token: str) -> list:
    data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
    out = []
    for j in data.get("jobs", []):
        out.append({
            "company": token, "source": "greenhouse", "title": j.get("title", ""),
            "location": (j.get("location") or {}).get("name", ""),
            "url": j.get("absolute_url", ""), "text": clean_text(j.get("content", "")),
        })
    return out


def lever(slug: str) -> list:
    data = _get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    out = []
    for j in data:
        cats = j.get("categories") or {}
        lists = " ".join(f"{x.get('text', '')} {clean_text(x.get('content', ''))}" for x in j.get("lists", []))
        out.append({
            "company": slug, "source": "lever", "title": j.get("text", ""),
            "location": cats.get("location", "") or "",
            "url": j.get("hostedUrl", ""),
            "text": clean_text(j.get("descriptionPlain", "") + " " + lists),
        })
    return out


def ashby(name: str) -> list:
    data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{name}")
    out = []
    for j in data.get("jobs", []):
        out.append({
            "company": name, "source": "ashby", "title": j.get("title", ""),
            "location": j.get("location", "") or "",
            "url": j.get("jobUrl", ""),
            "text": clean_text(j.get("descriptionPlain") or j.get("descriptionHtml") or ""),
        })
    return out


LOADERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}


def load_company(entry: str):
    """entry looks like 'greenhouse:databricks'. Returns (postings, error_or_None)."""
    kind, _, ident = entry.partition(":")
    loader = LOADERS.get(kind)
    if not loader or not ident:
        return [], f"bad entry {entry!r}"
    try:
        postings = loader(ident)
    except urllib.error.HTTPError as e:
        return [], f"HTTP {e.code}"
    except Exception as e:  # network or JSON problem: report, never guess
        return [], f"{type(e).__name__}: {e}"
    finally:
        time.sleep(DELAY_SECONDS)
    return postings, None


def load_paste_dir(path: str) -> list:
    """Text you paste yourself (LinkedIn posts, Reddit threads, job descriptions)."""
    import os
    out = []
    if not os.path.isdir(path):
        return out
    for fn in sorted(os.listdir(path)):
        if fn.lower().endswith((".txt", ".md")):
            with open(os.path.join(path, fn), encoding="utf-8", errors="replace") as f:
                out.append({"company": "paste", "source": "paste", "title": fn,
                            "location": "", "url": "", "text": f.read()})
    return out
