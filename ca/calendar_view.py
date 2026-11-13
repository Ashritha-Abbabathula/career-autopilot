"""A live calendar page built from the bot's own database (the earlier prototype in the notes folder is untouched).

One self-contained HTML file: month grids, today highlighted, exam days marked, each day's items
by kind, and a click on a day lists everything. It is rebuilt every morning and on demand.
Her own work (college, LeetCode, GATE, YouTube) is shown plainly; the assistant's items are
labelled "needs your yes" or "only you can do".
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List

from . import deadlines, planner

KIND_LABEL = {"college": "College", "dsa": "LeetCode", "gate": "GATE", "youtube": "YouTube",
              "touch": "Only you can do", "ok": "Needs your yes", "info": "Good to know",
              "exam": "Exam", "due": "Deadline"}


def collect(conn, start: date, end: date, today: date) -> Dict[str, List[dict]]:
    """Everything on each day between start and end, as plain dicts."""
    days: Dict[str, List[dict]] = {}

    def add(day: str, item: dict) -> None:
        days.setdefault(day, []).append(item)

    for t in conn.execute("SELECT * FROM tasks WHERE planned_date BETWEEN ? AND ? AND status != 'moved' ORDER BY id",
                          (start.isoformat(), end.isoformat())):
        add(t["planned_date"], {"kind": t["kind"], "title": t["title"], "status": t["status"], "minutes": t["minutes"]})
    for e in conn.execute("SELECT * FROM events WHERE date BETWEEN ? AND ? ORDER BY id", (start.isoformat(), end.isoformat())):
        add(e["date"], {"kind": "exam" if planner.is_exam(e["title"]) else "info", "title": e["title"], "status": "todo", "minutes": 0})
    for d in deadlines.upcoming(conn, start, days=(end - start).days):
        if d.source != "next_action" or d.due >= today:
            add(d.due.isoformat(), {"kind": "due", "title": d.text, "status": "todo", "minutes": 0})
    return days


def render(conn, today: date, start: date, end: date) -> str:
    data = {"today": today.isoformat(), "start": start.isoformat(), "end": end.isoformat(),
            "labels": KIND_LABEL, "days": collect(conn, start, end, today)}
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", blob)


def write(conn, path, today: date, start: date = None, end: date = None) -> Path:
    start = start or today.replace(day=1)
    end = end or (today + timedelta(days=120))
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(conn, today, start, end), encoding="utf-8")
    return out


TEMPLATE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Live calendar</title>
<style>
:root{--bg:#fbfaf7;--card:#fff;--ink:#1c1b19;--muted:#76726a;--line:#d9d5cc;--acc:#2b5fd9;--accs:#e7eefc;--red:#c0392b;--reds:#fbe9e7}
@media (prefers-color-scheme:dark){:root{--bg:#141516;--card:#1d1f21;--ink:#ecebe7;--muted:#9a978f;--line:#34363a;--acc:#7aa2ff;--accs:#1e2a45;--red:#ff8a7a;--reds:#3a1f1c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:0 8px 60px}
h1{font-size:18px;margin:14px 0 2px}.sub{color:var(--muted);font-size:13px;margin:0 0 6px}
.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin:6px 0 4px}.legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:4px}
.mh{margin:22px 0 0;text-align:center;font-size:clamp(22px,5vw,34px);font-weight:800;text-transform:uppercase;letter-spacing:.02em;border:1px solid var(--line);background:var(--card);padding:10px}
.wd,.grid{display:grid;grid-template-columns:repeat(7,1fr)}
.wd div{text-align:center;font-size:12px;color:var(--muted);padding:5px 0;border:1px solid var(--line);border-top:0;background:var(--card)}
.grid{border-left:1px solid var(--line)}
.cell{min-height:104px;padding:4px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);background:var(--card);cursor:pointer;font-size:11.5px;min-width:0;overflow:hidden}
.cell.blank{background:transparent;cursor:default}.cell.exam{background:var(--reds)}.cell.today{box-shadow:inset 0 0 0 2px var(--acc)}.cell.sel{background:var(--accs)}
.n{font-size:13px;font-weight:600}.r{display:flex;gap:4px;align-items:flex-start;line-height:1.2;margin-top:2px}.r.done{opacity:.45;text-decoration:line-through}
.dot{flex:none;width:7px;height:7px;border-radius:50%;margin-top:3px}
.k-dsa{background:#e08a1e}.k-gate{background:#2b5fd9}.k-youtube{background:#d33}.k-college{background:#2a9d6f}.k-exam{background:#c0392b}.k-due{background:#8e44ad}.k-touch{background:#555}.k-ok{background:#1f8f5f}.k-info{background:#999}
#detail{position:sticky;bottom:0;background:var(--card);border:1px solid var(--line);padding:10px 12px;margin-top:10px;display:none}
#detail h3{margin:0 0 6px;font-size:14px}#detail div{font-size:13px;padding:2px 0}
@media (max-width:640px){.cell{min-height:64px;font-size:10px}.r span:last-child{display:none}.r.keep span:last-child{display:inline}}
</style></head><body><div class="wrap">
<h1>Live calendar</h1><p class="sub" id="sub"></p><div class="legend" id="legend"></div>
<div id="months"></div><div id="detail"></div></div>
<script>
const D=__DATA__;const days=D.days;const $=id=>document.getElementById(id);
$("sub").textContent="Built from your plan and tracker. Today is "+D.today+". Tap a day for the full list.";
$("legend").innerHTML=["dsa","gate","youtube","college","exam","due","touch","ok"].map(k=>'<span><i class="dot k-'+k+'" style="display:inline-block"></i>'+D.labels[k]+'</span>').join("");
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const iso=d=>d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0");
function build(){let out="";const s=new Date(D.start+"T00:00:00"),e=new Date(D.end+"T00:00:00");
let m=new Date(s.getFullYear(),s.getMonth(),1);
while(m<=e){const name=m.toLocaleString("en",{month:"long",year:"numeric"});
out+='<div class="mh">'+name+'</div><div class="wd">'+["Mon","Tue","Wed","Thu","Fri","Sat","Sun"].map(x=>"<div>"+x+"</div>").join("")+'</div><div class="grid">';
const first=(m.getDay()+6)%7,len=new Date(m.getFullYear(),m.getMonth()+1,0).getDate();
for(let i=0;i<first;i++)out+='<div class="cell blank"></div>';
for(let d=1;d<=len;d++){const dt=new Date(m.getFullYear(),m.getMonth(),d),key=iso(dt),items=days[key]||[];
const cls=["cell"];if(key===D.today)cls.push("today");if(items.some(x=>x.kind==="exam"))cls.push("exam");
const rows=items.slice(0,4).map(x=>'<div class="r '+(x.status==="done"?"done":"")+' '+(x.kind==="exam"||x.kind==="due"?"keep":"")+'"><i class="dot k-'+x.kind+'"></i><span>'+esc(x.title.length>34?x.title.slice(0,32)+"…":x.title)+'</span></div>').join("");
out+='<div class="'+cls.join(" ")+'" data-d="'+key+'"><div class="n">'+d+'</div>'+rows+(items.length>4?'<div class="r"><span>+'+(items.length-4)+' more</span></div>':'')+'</div>';}
out+="</div>";m=new Date(m.getFullYear(),m.getMonth()+1,1);}
$("months").innerHTML=out;
document.querySelectorAll(".cell[data-d]").forEach(c=>c.addEventListener("click",()=>show(c.dataset.d,c)));}
function show(key,cell){document.querySelectorAll(".cell.sel").forEach(x=>x.classList.remove("sel"));cell.classList.add("sel");
const items=days[key]||[];const box=$("detail");box.style.display="block";
box.innerHTML="<h3>"+key+"</h3>"+(items.length?items.map(x=>"<div>"+(x.status==="done"?"[done] ":x.status==="skipped"?"[skipped] ":"")+"<b>"+esc(D.labels[x.kind]||x.kind)+":</b> "+esc(x.title)+(x.minutes?" ("+x.minutes+" min)":"")+"</div>").join(""):"<div>Nothing planned.</div>");}
build();const t=document.querySelector(".cell.today");if(t)t.scrollIntoView({block:"center"});
</script></body></html>"""
