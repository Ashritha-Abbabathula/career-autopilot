"""The owner's original 90-day plan page, run as the calendar.

Her page (calendar/original_plan.html in the private folder) is used as it is, so everything it does keeps
working: the Oct 4 to Feb 5 grid, ticks, the Pomodoro timer with its time-worked log, sticky notes, day
photos, misc college work you can drag between days, the progress bars, the PDF export.

Two things are added, and nothing in her page is rewritten:
1. Storage: her page saved to one browser's localStorage. Here it saves to the bot's database instead (and the
   offline file keeps its own copy), so your ticks and notes live on the server and the bot knows them.
2. An overlay: the assistant's items (needs your OK, only you can do, dates to know), deadlines, and your real
   past LeetCode and GitHub activity are shown on the same days, with Approve / Skip / Later where it applies.
The original file is private (it holds your timetable); this module only knows how to wrap it.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from . import calendar_view, deadlines, uistate

LS_LINE = re.compile(r"^const ls=\{get\(k\)\{.*?\};\s*$", re.M)

STORAGE_JS = r"""const ls=(()=>{const S=window.__STATE__||{},SRV=location.protocol==="http:"||location.protocol==="https:";
const raw={get(k){try{return localStorage.getItem(k)}catch(e){return null}},set(k,v){try{localStorage.setItem(k,v);return true}catch(e){return false}},del(k){try{localStorage.removeItem(k)}catch(e){}}};
const post=(k,v)=>{try{fetch("/api/state",{method:"POST",headers:{"Content-Type":"application/json","X-Calendar":"1"},body:JSON.stringify({k:k,v:v})}).catch(()=>{})}catch(e){}};
if(SRV)return{get:k=>(k in S?S[k]:null),set:(k,v)=>{S[k]=String(v);post(k,String(v));return true},del:k=>{delete S[k];post(k,null)}};
return{get:k=>{const x=raw.get(k);return x!==null?x:(k in S?S[k]:null)},set:raw.set,del:raw.del}})();"""

OVERLAY_JS = r"""
const EX=window.__EXTRA__||{},XSRV=location.protocol==="http:"||location.protocol==="https:";
const XCOL={ok:"#d9822b",touch:"#d4537e",info:"#8a8a8a",due:"#7d3c98",hist:"#3b8f5a"};
const XNAME={ok:"Needs your OK",touch:"Needs you",info:"Date to know",due:"Deadline",hist:"Past activity"};
const xesc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const xdone=it=>!!it.done||(it.dec&&it.dec!=="later");
if(!XSRV){try{const o=JSON.parse(ls.get("x-state")||"{}");for(const k in EX)for(const it of EX[k]){const s=o[it.id];if(s){if(s.done!=null)it.done=s.done;if(s.dec)it.dec=s.dec}}}catch(e){}}
const xsave=()=>{if(XSRV)return;const o={};for(const k in EX)for(const it of EX[k])if(it.done||it.dec)o[it.id]={done:it.done,dec:it.dec};ls.set("x-state",JSON.stringify(o))};
const xpost=(p,b)=>fetch(p,{method:"POST",headers:{"Content-Type":"application/json","X-Calendar":"1"},body:JSON.stringify(b)}).then(r=>{if(!r.ok)throw new Error("save failed")});
const _cell=cell;
cell=function(d){const h=_cell(d),k=key(d),L=EX[k]||[];if(!L.length)return h;
  const rows=L.slice(0,3).map(it=>'<span class="r'+(xdone(it)?' dn':'')+'" style="--c:'+XCOL[it.stream]+'"><span>'+(xdone(it)?'&#10003; ':'')+xesc(it.title)+'</span></span>').join("")+(L.length>3?'<span class="r"><span>+'+(L.length-3)+' more</span></span>':'');
  const planned=/^<button class="cell plan/.test(h)?h:h.replace('class="cell','class="cell plan');
  return planned.replace(/<\/button>$/,rows+'</button>')};
const _open=open;
open=function(k){_open(k);const L=EX[k]||[];if(!L.length)return;
  const h='<details class="part" open style="--c:#d9822b"><summary><b>From your assistant</b><span class="t">'+L.length+'</span></summary><ul class="pl">'+L.map(it=>
   '<li><label><input type="checkbox" data-x="'+it.id+'" '+(xdone(it)?'checked ':'')+((it.stream==="hist"||it.stream==="due"||it.stream==="ok")?'disabled':'')+'><span><span class="b" style="background:'+XCOL[it.stream]+'">'+XNAME[it.stream]+'</span> '+xesc(it.title)+'</span></label>'
   +(it.detail?'<div class="sub">'+xesc(it.detail)+'</div>':'')
   +(it.stream==="ok"?'<div class="btns">'+["approve","skip","later"].map(a=>'<button class="btn'+(it.dec===a?' on':'')+'" data-xid="'+it.id+'" data-xa="'+a+'">'+a[0].toUpperCase()+a.slice(1)+'</button>').join("")+'</div>':'')+'</li>').join("")+'</ul></details>';
  box.insertAdjacentHTML("beforeend",h)};
const xfind=id=>{for(const k in EX)for(const it of EX[k])if(it.id===id)return[k,it];return[null,null]};
const xrefresh=k=>{upd(k);open(k)};
box.addEventListener("change",e=>{const t=e.target,id=t.dataset&&t.dataset.x;if(!id)return;const[k,it]=xfind(id);if(!it)return;
  const on=t.checked,apply=()=>{it.done=on;xsave();xrefresh(k)};
  if(XSRV)xpost("/api/tick",{id:id,done:on}).then(apply).catch(()=>{t.checked=!on});else apply()});
box.addEventListener("click",e=>{const t=e.target,id=t.dataset&&t.dataset.xid;if(!id)return;const a=t.dataset.xa,[k,it]=xfind(id);if(!it)return;
  const apply=()=>{it.dec=a;it.done=(a==="approve");xsave();xrefresh(k)};
  if(XSRV)xpost("/api/decide",{id:id,action:a}).then(apply).catch(()=>{});else apply()});
{const n=document.createElement("p");n.className="sub";n.style.margin="2px 0 0";
 n.textContent=XSRV?"Saved to the bot: your ticks, notes, Pomodoro time and photos are remembered by the assistant.":"Offline copy: changes stay in this browser. Ticks and notes made on the bot's own page are kept by the assistant.";
 const top=document.querySelector(".top");if(top)top.appendChild(n)}
render();
"""


def available(private_dir) -> bool:
    return bool(private_dir) and (Path(private_dir) / "calendar" / "original_plan.html").is_file()


def extras(conn, start: date, end: date, today: date) -> Dict[str, List[dict]]:
    """The assistant's own items for the overlay: dated items it created, deadlines, and past activity."""
    out: Dict[str, List[dict]] = {}

    def add(day: str, item: dict) -> None:
        out.setdefault(day, []).append(item)

    for t in conn.execute("SELECT * FROM tasks WHERE source = 'plan_item' AND status != 'moved' ORDER BY id"):
        item = {"id": f"t{t['id']}", "stream": t["kind"] if t["kind"] in ("ok", "touch", "info") else "info",
                "title": t["title"], "done": t["status"] == "done"}
        detail = calendar_view._meta(t["meta"]).get("detail")
        if detail:
            item["detail"] = detail
        if t["kind"] == "ok" and t["status"] in ("done", "skipped"):
            item["dec"] = "approve" if t["status"] == "done" else "skip"
        add(t["planned_date"], item)
    n = 0
    for d in deadlines.upcoming(conn, start, days=(end - start).days):
        if d.source != "next_action" or d.due >= today:
            n += 1
            add(d.due.isoformat(), {"id": f"d{n}", "stream": "due", "title": d.text, "done": False})
    hist = calendar_view.load_history(conn)
    for source, label, unit in (("leetcode", "LeetCode", "submission"), ("github", "GitHub", "commit")):
        for day, count in sorted(hist.get(source, {}).items()):
            if day <= today.isoformat() and count:
                add(day, {"id": f"h-{source}-{day}", "stream": "hist", "done": True,
                          "title": f"{label}: {count} {unit}{'s' if count != 1 else ''} (your public profile)"})
    return out


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def wrap(original_html: str, state: Dict[str, str], extra: Dict[str, List[dict]]) -> str:
    """Her page with the storage swapped and the overlay added. Raises ValueError if her page's storage
    line is not where this expects it (so a changed page is noticed, not silently broken)."""
    if not LS_LINE.search(original_html):
        raise ValueError("the original page's storage line was not found")
    html = LS_LINE.sub(lambda m: STORAGE_JS, original_html, count=1)
    seed = f"<script>window.__STATE__={_json(state)};window.__EXTRA__={_json(extra)};</script>\n<script>"
    html = html.replace("<script>", seed, 1)
    # her script ends with "render();disp();rn();" and then </script>; the overlay runs after it in a second script
    return html.replace("</script></body></html>", "</script><script>" + OVERLAY_JS + "</script></body></html>", 1)


def render(conn, private_dir, today: date) -> Optional[str]:
    """The page for today, or None when the original file is not in the private folder."""
    path = Path(private_dir) / "calendar" / "original_plan.html"
    if not path.is_file():
        return None
    start, end = date(2026, 10, 4), date(2027, 2, 5)
    return wrap(path.read_text(encoding="utf-8"), uistate.snapshot(conn), extras(conn, start, end, today))
