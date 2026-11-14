"""The live calendar page, built from the bot's database. It keeps everything the original prototype
(notes folder, left untouched) does: month grids from 14 Nov to 5 Feb, the day popup with tick boxes,
problem and video links, the progress bars that start from what you had already done, the
Approve / Skip / Later buttons on the assistant's items, and the decisions export.

Two ways to open it:
- through the bot's local page (http://localhost:8765/): ticks and decisions are saved straight into
  the bot's database, so `today` and the evening check-in know about them;
- as the saved file (live_calendar.html): works offline; ticks stay in the browser, as in the original.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List

from . import db, deadlines, planner

STREAM = {"dsa": "dsa", "youtube": "yt", "gate": "gate", "college": "college", "touch": "touch", "ok": "ok", "info": "info"}
EXAM_DETAIL = "Exam day. Nothing else matters today except the one LeetCode problem if you can."


def _meta(raw: str) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def plan_info(conn) -> dict:
    try:
        return json.loads(db.get_setting(conn, "plan_info", "") or "{}")
    except ValueError:
        return {}


def load_history(conn) -> dict:
    """Past activity saved by the daily history job: {"leetcode": {day: n}, "github": {day: n}}."""
    try:
        data = json.loads(db.get_setting(conn, "history_json", "") or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def save_history(conn, leetcode_days, github_days) -> None:
    """Merge newly read days into what is saved; a failed read (None) keeps what we already had."""
    data = load_history(conn)
    for name, days in (("leetcode", leetcode_days), ("github", github_days)):
        if days:
            merged = dict(data.get(name, {}))
            merged.update(days)
            data[name] = merged
    db.set_setting(conn, "history_json", json.dumps(data))


def collect(conn, start: date, end: date, today: date) -> Dict[str, List[dict]]:
    """Everything on each day between start and end, as plain dicts the page can use."""
    days: Dict[str, List[dict]] = {}

    def add(day: str, item: dict) -> None:
        days.setdefault(day, []).append(item)

    for e in conn.execute("SELECT * FROM events WHERE date BETWEEN ? AND ? ORDER BY id", (start.isoformat(), end.isoformat())):
        exam = planner.is_exam(e["title"])
        add(e["date"], {"id": f"e{e['id']}", "stream": "fat" if exam else "info", "title": e["title"],
                        "detail": EXAM_DETAIL if exam else "", "done": False})
    for t in conn.execute("SELECT * FROM tasks WHERE planned_date BETWEEN ? AND ? AND status != 'moved' ORDER BY id",
                          (start.isoformat(), end.isoformat())):
        meta = _meta(t["meta"])
        item = {"id": f"t{t['id']}", "stream": STREAM.get(t["kind"], "info"), "title": t["title"],
                "done": t["status"] == "done", "skipped": t["status"] == "skipped"}
        for key in ("link", "links", "detail"):
            if meta.get(key):
                item[key] = meta[key]
        if t["kind"] == "ok" and t["status"] in ("done", "skipped"):
            item["dec"] = "approve" if t["status"] == "done" else "skip"
        add(t["planned_date"], item)
    hist = load_history(conn)
    for source, label, unit in (("leetcode", "LeetCode", "submission"), ("github", "GitHub", "commit")):
        for day, count in sorted(hist.get(source, {}).items()):
            if start.isoformat() <= day <= min(end, today).isoformat() and count:
                add(day, {"id": f"h-{source}-{day}", "stream": "hist", "done": True,
                          "title": f"{label}: {count} {unit}{'s' if count != 1 else ''}"})
    n = 0
    for d in deadlines.upcoming(conn, start, days=(end - start).days):
        if d.source != "next_action" or d.due >= today:
            n += 1
            add(d.due.isoformat(), {"id": f"d{n}", "stream": "due", "title": d.text, "done": False})
    return days


def render(conn, today: date, start: date, end: date) -> str:
    info = plan_info(conn)
    data = {"today": today.isoformat(), "start": start.isoformat(), "end": end.isoformat(),
            "base": info.get("base", {"dsa": 0, "youtube": 0, "gate": 0}),
            "totals": info.get("totals", {"dsa": 0, "youtube": 0, "gate": 0}),
            "byDate": collect(conn, start, end, today)}
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", blob)


def span(conn, today: date):
    info = plan_info(conn)
    try:
        start, end = date.fromisoformat(info["start"]), date.fromisoformat(info["end"])
    except (KeyError, ValueError):
        start, end = today.replace(day=1), today + timedelta(days=120)
    hist = load_history(conn)
    past = [d for source in hist.values() for d in source if isinstance(d, str)]
    if past:                                           # show earlier months too, back to the first day of recorded activity
        try:
            earliest = date.fromisoformat(min(past))
            start = min(start, earliest.replace(day=1))
        except ValueError:
            pass
    return min(start, today), max(end, today)


def write(conn, path, today: date, start: date = None, end: date = None, private_dir: str = "") -> Path:
    """Save the calendar as a file. With the owner's original page in the private folder, that page is the file."""
    from . import original_page
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    html = original_page.render(conn, private_dir, today) if private_dir else None
    if html is None:
        s, e = span(conn, today)
        html = render(conn, today, start or s, end or e)
    out.write_text(html, encoding="utf-8")
    return out


# ---- changes made from the page --------------------------------------------
def apply_tick(conn, item_id: str, done: bool) -> bool:
    """Tick or untick a planned task from the page. Only tasks (ids like t12) can be changed."""
    if not item_id.startswith("t") or not item_id[1:].isdigit():
        return False
    row = conn.execute("SELECT status FROM tasks WHERE id = ?", (int(item_id[1:]),)).fetchone()
    if row is None or row["status"] == "moved":
        return False
    conn.execute("UPDATE tasks SET status = ? WHERE id = ?", ("done" if done else "todo", int(item_id[1:])))
    conn.commit()
    return True


def apply_decision(conn, item_id: str, action: str) -> bool:
    """Approve, skip or later on one of the assistant's items (kind 'ok'). Later leaves it waiting."""
    if action not in ("approve", "skip", "later") or not item_id.startswith("t") or not item_id[1:].isdigit():
        return False
    row = conn.execute("SELECT kind FROM tasks WHERE id = ?", (int(item_id[1:]),)).fetchone()
    if row is None or row["kind"] != "ok":
        return False
    status = {"approve": "done", "skip": "skipped", "later": "todo"}[action]
    conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, int(item_id[1:])))
    conn.commit()
    return True


TEMPLATE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Career calendar</title>
<style>
:root{--bg:#fbfaf7;--card:#fff;--ink:#1c1b19;--muted:#76726a;--line:#d9d5cc;--acc:#2b5fd9;--accs:#e7eefc;--ok:#1f8f5f;box-sizing:border-box}
@media (prefers-color-scheme:dark){:root{--bg:#141516;--card:#1d1f21;--ink:#ecebe7;--muted:#9a978f;--line:#34363a;--acc:#7aa2ff;--accs:#1e2a45;--ok:#4cc38a}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:0 8px 80px}
.top{position:sticky;top:0;background:var(--bg);padding:12px 0 8px;z-index:5;border-bottom:1px solid var(--line)}
h1{margin:0;font-size:18px}.sub{margin:4px 0 8px;color:var(--muted);font-size:13px}
.bars{display:grid;grid-template-columns:repeat(4,1fr);gap:6px 10px}.bars span{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-bottom:2px}.bars b{color:var(--ink);font-weight:600}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden}.bar i{display:block;height:100%;width:0}
@media (max-width:520px){.bars{grid-template-columns:repeat(2,1fr)}}
.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-top:8px}
.legend i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px}
.btn{border:1px solid var(--line);background:var(--card);border-radius:8px;padding:6px 12px;cursor:pointer;color:var(--ink);font:inherit}
.btn.p{background:var(--acc);color:#fff;border-color:var(--acc)}
.mh{margin:22px 0 0;text-align:center;font-size:clamp(24px,5vw,38px);font-weight:800;letter-spacing:.02em;text-transform:uppercase;border:1px solid var(--line);background:var(--card);padding:12px}
.wd,.grid{display:grid;grid-template-columns:repeat(7,1fr)}
.wd span{text-align:center;font-size:12px;color:var(--muted);padding:6px 0;border:1px solid var(--line);border-top:0;background:var(--card)}
.grid{border-left:1px solid var(--line)}
.cell{box-sizing:border-box;min-height:110px;padding:5px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);background:var(--card);cursor:pointer;display:flex;flex-direction:column;gap:3px;font-size:12px;min-width:0}
.cell.blank{background:transparent;cursor:default}.cell.plan{background:var(--accs)}.cell.today{box-shadow:inset 0 0 0 2px var(--acc)}
.num{font-size:14px}
.r{display:flex;gap:4px;align-items:flex-start;font-size:10px;line-height:1.2}
.r::before{content:"";flex:none;width:6px;height:6px;border-radius:50%;background:var(--c);margin-top:3px}
.r span{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;word-break:break-word}
.r.dn{color:var(--ok);font-weight:700}
@media (min-width:700px){.cell{min-height:124px}.r{font-size:11px}}
.sheet{position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:flex-end;justify-content:center;z-index:10}
.sheet[hidden]{display:none}
.box{position:relative;background:var(--card);width:100%;max-width:640px;max-height:90vh;overflow:auto;border-radius:16px 16px 0 0;padding:20px}
@media (min-width:600px){.sheet{align-items:center}.box{border-radius:16px}}
.box h3{margin:0 28px 2px 0;font-size:17px}.xx{position:absolute;top:10px;right:16px;font-size:26px;cursor:pointer;color:var(--muted);background:none;border:0}
.it{padding:9px 0;border-top:1px solid var(--line)}
.it label{display:flex;gap:10px;align-items:flex-start;cursor:pointer}
.it a{color:var(--acc)}.det{color:var(--muted);font-size:12px;margin:3px 0 0 26px}
.acts{display:flex;gap:6px;margin:6px 0 0 26px;flex-wrap:wrap}
.tag{font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;color:#fff;margin-right:6px}
.dec{font-size:12px;margin-left:26px;color:var(--ok)}
.mode{font-size:12px;color:var(--muted)}
</style></head><body><div class="wrap">
<div class="top"><div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap"><h1>Career calendar &middot; <span id="range"></span></h1><div style="display:flex;gap:6px"><button class="btn" id="exp">Export my decisions</button></div></div>
<p class="sub">Your own work is only four things: college (FAT prep and exams), LeetCode, GATE and YouTube. Everything else is prepared by the assistant and waits for your OK. Tap any day. <span class="mode" id="mode"></span></p>
<div class="bars" id="bars"></div>
<div class="legend" id="legend"></div></div>
<div id="cal"></div></div>
<div class="sheet" id="sheet" hidden><div class="box" id="box"></div></div>
<script>
const D=__DATA__;
const SERVER=location.protocol==="http:"||location.protocol==="https:";
const COL={dsa:"#2b5fd9",yt:"#8a55c8",gate:"#2a9d8f",college:"#6b6f76",fat:"#c8472b",ok:"#d9822b",touch:"#d4537e",info:"#8a8a8a",due:"#7d3c98",hist:"#3b8f5a"};
const NAME={dsa:"LeetCode",yt:"YouTube",gate:"GATE",college:"College",fat:"FAT exam",ok:"Needs your OK",touch:"Needs you",info:"Date to know",due:"Deadline",hist:"Past activity"};
const MN=["January","February","March","April","May","June","July","August","September","October","November","December"],WD=["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
const ls={get(k){try{return localStorage.getItem(k)}catch(e){return null}},set(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
let st={done:{},dec:{}};
for(const k in D.byDate)for(const it of D.byDate[k]){if(it.done)st.done[it.id]=1;if(it.dec)st.dec[it.id]=it.dec}
if(!SERVER){try{const l=JSON.parse(ls.get("cc-state-v1"))||{};Object.assign(st.done,l.done||{});Object.assign(st.dec,l.dec||{})}catch(e){}}
const save=()=>{if(!SERVER)ls.set("cc-state-v1",JSON.stringify(st))};
const $=i=>document.getElementById(i),key=(y,m,d)=>y+"-"+String(m+1).padStart(2,"0")+"-"+String(d).padStart(2,"0");
const todayKey=D.today;
const fmt=s=>{const d=new Date(s+"T00:00:00");return d.getDate()+" "+MN[d.getMonth()].slice(0,3)};
$("range").textContent=fmt(D.start)+" to "+fmt(D.end);
$("mode").textContent=SERVER?"Saved to the bot: ticks and decisions are remembered by the assistant.":"Opened as a file: ticks stay in this browser only. Open http://localhost:8765/ while the bot runs to save them to the assistant.";
const isDone=it=>!!st.done[it.id]||(st.dec[it.id]&&st.dec[it.id]!=="later");
function post(path,body){return fetch(path,{method:"POST",headers:{"Content-Type":"application/json","X-Calendar":"1"},body:JSON.stringify(body)}).then(r=>{if(!r.ok)throw new Error("save failed")})}
function bars(){
  const rows=[["LeetCode","dsa",D.base.dsa,D.totals.dsa],["GATE","gate",D.base.gate,D.totals.gate],["YouTube","yt",D.base.youtube,D.totals.youtube]];
  let h="";
  for(const[l,s,b,tot]of rows){let n=0;
    for(const k in D.byDate){const xs=D.byDate[k].filter(it=>it.stream===s);if(!xs.length)continue;
      if(s==="gate"){if(xs.every(isDone))n++}else n+=xs.filter(isDone).length}
    const v=Math.min(tot,b+n);
    h+='<div><span>'+l+'<b>'+v+'/'+tot+'</b></span><div class="bar"><i style="width:'+(tot?100*v/tot:0)+'%;background:'+COL[s]+'"></i></div></div>'}
  let pn=0,pt=0;for(const k in D.byDate)for(const it of D.byDate[k])if(it.stream==="college"){pt++;if(isDone(it))pn++}
  h+='<div><span>FAT prep<b>'+pn+'/'+pt+'</b></span><div class="bar"><i style="width:'+(pt?100*pn/pt:0)+'%;background:'+COL.college+'"></i></div></div>';
  $("bars").innerHTML=h}
function legend(){$("legend").innerHTML=["dsa","gate","yt","college","fat","ok","touch","info","due","hist"].map(s=>'<span><i style="background:'+COL[s]+'"></i>'+NAME[s]+'</span>').join("")}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function render(){
  const cal=$("cal");cal.innerHTML="";const a=new Date(D.start+"T00:00:00"),b=new Date(D.end+"T00:00:00");
  let y=a.getFullYear(),m=a.getMonth();
  while(y<b.getFullYear()||(y===b.getFullYear()&&m<=b.getMonth())){
    const h=document.createElement("div");h.className="mh";h.textContent=MN[m]+" "+y;cal.appendChild(h);
    const w=document.createElement("div");w.className="wd";w.innerHTML=WD.map(x=>"<span>"+x+"</span>").join("");cal.appendChild(w);
    const g=document.createElement("div");g.className="grid";
    const first=new Date(y,m,1).getDay(),days=new Date(y,m+1,0).getDate();
    for(let i=0;i<first;i++){const c=document.createElement("div");c.className="cell blank";g.appendChild(c)}
    for(let d=1;d<=days;d++){
      const k=key(y,m,d),its=D.byDate[k]||[];const c=document.createElement("div");
      c.className="cell"+(its.length?" plan":"")+(k===todayKey?" today":"");c.setAttribute("role","button");c.tabIndex=0;c.dataset.d=k;
      c.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();openDay(k)}};
      let inner='<div class="num">'+d+'</div>';
      const shown=its.slice(0,5);
      for(const it of shown){inner+='<div class="r'+(isDone(it)?' dn':'')+'" style="--c:'+COL[it.stream]+'"><span>'+(isDone(it)?'&#10003; ':'')+esc(it.title)+'</span></div>'}
      if(its.length>shown.length)inner+='<div class="r" style="--c:#999"><span>+'+(its.length-shown.length)+' more</span></div>';
      c.innerHTML=inner;c.onclick=()=>openDay(k);g.appendChild(c)}
    cal.appendChild(g);m++;if(m>11){m=0;y++}}
  bars()}
function openDay(k){
  const its=D.byDate[k]||[];const dd=new Date(k+"T00:00:00");
  let h='<button class="xx" onclick="closeS()" aria-label="Close">&times;</button><h3>'+WD[dd.getDay()]+" "+dd.getDate()+" "+MN[dd.getMonth()]+'</h3><p class="sub">'+(its.length?its.length+" items":"Free day")+'</p>';
  for(const it of its){
    const locked=(it.stream==="ok"||it.stream==="hist"||(SERVER&&it.id[0]!=="t"));
    h+='<div class="it"><label><input type="checkbox" '+(isDone(it)?"checked":"")+' data-id="'+it.id+'" '+(locked?"disabled":"")+'><span><span class="tag" style="background:'+COL[it.stream]+'">'+NAME[it.stream]+'</span>'+esc(it.title)+'</span></label>';
    if(it.link)h+='<div class="det"><a href="'+esc(it.link)+'" target="_blank" rel="noopener">Open problem</a></div>';
    if(it.links&&it.links.length)h+='<div class="det">'+it.links.map(l=>'<a href="'+esc(l[1])+'" target="_blank" rel="noopener">'+esc(l[0])+'</a>').join(" &middot; ")+'</div>';
    if(it.detail)h+='<div class="det">'+esc(it.detail)+'</div>';
    if(it.stream==="ok"){const cur=st.dec[it.id];h+='<div class="acts">'+["approve","skip","later"].map(a=>'<button class="btn'+(cur===a?" p":"")+'" data-id="'+it.id+'" data-a="'+a+'">'+a[0].toUpperCase()+a.slice(1)+'</button>').join("")+'</div>'+(cur?'<div class="dec">Your decision: '+cur+'</div>':"")}
    h+='</div>'}
  $("box").innerHTML=h;$("sheet").hidden=false;
  const flash=msg=>{const s=$("box").querySelector(".sub");if(s)s.textContent=msg};
  $("box").querySelectorAll("input[type=checkbox]").forEach(x=>x.onchange=()=>{
    const id=x.dataset.id,on=x.checked;
    const apply=()=>{if(on)st.done[id]=1;else delete st.done[id];save();render();openDay(k)};
    if(SERVER)post("/api/tick",{id:id,done:on}).then(apply).catch(()=>{x.checked=!on;flash("Could not save. Is the bot running?")});else apply()});
  $("box").querySelectorAll("button[data-a]").forEach(x=>x.onclick=()=>{
    const id=x.dataset.id,a=x.dataset.a;
    const apply=()=>{st.dec[id]=a;save();render();openDay(k)};
    if(SERVER)post("/api/decide",{id:id,action:a}).then(apply).catch(()=>flash("Could not save. Is the bot running?"));else apply()})}
function closeS(){$("sheet").hidden=true}
$("sheet").onclick=e=>{if(e.target.id==="sheet")closeS()};
$("exp").onclick=()=>{
  let rows=["date,id,title,decision"];
  for(const k in D.byDate)for(const it of D.byDate[k])if(it.stream==="ok"&&st.dec[it.id])rows.push([k,it.id,'"'+it.title.replace(/"/g,'""')+'"',st.dec[it.id]].join(","));
  const blob=new Blob([rows.join("\n")],{type:"text/csv"}),a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="my-decisions.csv";a.click()};
legend();render();
const tc=document.querySelector(".cell.today");if(tc)tc.scrollIntoView({block:"center"});
</script></body></html>"""
