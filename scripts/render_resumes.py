"""Render every resume variant from the private facts file into HTML drafts.

    python scripts/render_resumes.py [facts.json] [out_folder]

Drafts show unverified facts with a red [verify] tag. Print the HTML to PDF from the browser.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ca import facts, resume  # noqa: E402

PRIVATE = Path(__file__).resolve().parent.parent.parent / "notebooks" / "09-career-autopilot" / "facts"


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else PRIVATE / "facts.json"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else PRIVATE / "drafts"
    out.mkdir(parents=True, exist_ok=True)
    data = facts.load(src)
    for name, problem in resume.check_all(data).items():
        print(f"{name}: {'passes the fact checks (add your contact details before sending)' if problem is None else 'NOT READY: ' + problem}")
        (out / f"{name}.html").write_text(resume.render_resume(data, name, allow_unverified=True), encoding="utf-8")
    print("drafts written to", out)


if __name__ == "__main__":
    main()
