#!/usr/bin/env python3
"""
Multi-Agent Terrain Scanner — All-in-One Dashboard

Everything in one place: create accounts, promote to GM, scan terrain.
Run: python3 dashboard.py
Open: http://localhost:5556
"""
from __future__ import annotations

import json
import os
import sys
import time
import threading
from pathlib import Path

from flask import Flask, request, jsonify, render_template_string, Response

sys.path.insert(0, os.path.dirname(__file__))
from scan_state import ScanProgress
from scan_manager import ScanManager

app = Flask(__name__)

# Global state
progress = ScanProgress(db_path=str(Path(__file__).parent / "scan_progress.db"))
manager = ScanManager(progress)


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/status")
def api_status():
    return jsonify(manager.get_status())


@app.route("/api/events")
def api_events():
    def generate():
        q = progress.subscribe_sse()
        try:
            while True:
                try:
                    event = q.get(timeout=30)
                    data = json.dumps(event)
                    yield f"event: {event['type']}\ndata: {data}\n\n"
                except Exception:
                    yield f": keepalive\n\n"
        finally:
            progress.unsubscribe_sse(q)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/bootstrap", methods=["POST"])
def api_bootstrap():
    """Create accounts + characters + promote to GM."""
    data = request.json or {}
    num = int(data.get("num", 20))
    promote = data.get("promote", True)

    manager.login_host = data.get("login_host", manager.login_host)
    manager.login_port = int(data.get("login_port", manager.login_port))
    manager.account_prefix = data.get("prefix", manager.account_prefix)
    manager.password = data.get("password", manager.password)
    manager.db_name = data.get("db_name", manager.db_name)
    manager.db_user = data.get("db_user", manager.db_user)

    def run():
        manager.bootstrap(num, promote=promote)

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"status": "started", "num": num, "promote": promote})


@app.route("/api/scan/start", methods=["POST"])
def api_scan_start():
    data = request.json or {}
    num_workers = int(data.get("num_workers", 20))
    scan_mode = data.get("scan_mode", "block")

    manager.login_host = data.get("login_host", manager.login_host)
    manager.login_port = int(data.get("login_port", manager.login_port))
    manager.account_prefix = data.get("prefix", manager.account_prefix)
    manager.password = data.get("password", manager.password)
    manager.output_dir = data.get("output_dir", "")

    def start():
        manager.start(num_workers=num_workers, scan_mode=scan_mode)

    threading.Thread(target=start, daemon=True).start()
    return jsonify({"status": "started", "num_workers": num_workers, "scan_mode": scan_mode})


@app.route("/api/scan/stop", methods=["POST"])
def api_scan_stop():
    threading.Thread(target=manager.stop, daemon=True).start()
    return jsonify({"status": "stopping"})


@app.route("/api/worker/add", methods=["POST"])
def api_worker_add():
    data = request.json or {}
    name = data.get("name", "")
    manager.add_worker(name)
    return jsonify({"status": "added", "name": name})


@app.route("/api/worker/remove", methods=["POST"])
def api_worker_remove():
    data = request.json or {}
    name = data.get("name", "")
    manager.remove_worker(name)
    return jsonify({"status": "removed", "name": name})


@app.route("/api/scan/reset", methods=["POST"])
def api_scan_reset():
    progress.reset()
    return jsonify({"status": "reset"})


# ============================================================================
# EMBEDDED HTML — ALL-IN-ONE DASHBOARD
# ============================================================================

HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>L2 Terrain Scanner</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: #0a0e14; color: #bfccd6; min-height: 100vh; }

/* Header */
.hdr { background: #0f1923; border-bottom: 1px solid #1a2332; padding: 10px 20px; display: flex; align-items: center; gap: 12px; }
.hdr h1 { font-size: 15px; color: #fff; font-weight: 700; letter-spacing: -0.3px; }
.hdr .tag { padding: 2px 10px; border-radius: 10px; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }
.hdr .tag.idle { background: #1a2332; color: #546e7a; }
.hdr .tag.run { background: #1b5e20; color: #69f0ae; }
.hdr .tag.boot { background: #e65100; color: #ffcc80; }
.hdr .clock { margin-left: auto; font-size: 11px; color: #546e7a; font-family: 'SF Mono', monospace; }

/* Main layout */
.main { display: grid; grid-template-columns: 280px 1fr; min-height: calc(100vh - 41px); }

/* Sidebar */
.side { background: #0f1923; border-right: 1px solid #1a2332; padding: 16px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; }
.card { background: #0a0e14; border: 1px solid #1a2332; border-radius: 8px; padding: 12px; }
.card h3 { font-size: 11px; color: #546e7a; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 10px; font-weight: 600; }
.card .step-num { display: inline-block; background: #1a2332; color: #39bae6; width: 18px; height: 18px; border-radius: 50%; text-align: center; line-height: 18px; font-size: 10px; font-weight: 700; margin-right: 4px; }

.fg { display: flex; flex-direction: column; gap: 4px; margin-bottom: 8px; }
.fg label { font-size: 10px; color: #546e7a; text-transform: uppercase; letter-spacing: 0.5px; }
.fg input, .fg select { font-family: inherit; font-size: 12px; padding: 6px 8px; border-radius: 6px; border: 1px solid #1a2332; background: #0d1219; color: #bfccd6; outline: none; width: 100%; }
.fg input:focus, .fg select:focus { border-color: #39bae6; }

.row { display: flex; gap: 6px; }
button { font-family: inherit; font-size: 11px; padding: 7px 14px; border-radius: 6px; border: none; cursor: pointer; font-weight: 600; transition: all 0.15s; }
button:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-go { background: #39bae6; color: #0a0e14; }
.btn-go:hover:not(:disabled) { background: #59cbf7; }
.btn-green { background: #1b5e20; color: #69f0ae; }
.btn-green:hover:not(:disabled) { background: #2e7d32; }
.btn-red { background: #b71c1c; color: #ef9a9a; }
.btn-red:hover:not(:disabled) { background: #c62828; }
.btn-sec { background: #1a2332; color: #bfccd6; }
.btn-sec:hover:not(:disabled) { background: #253545; }

/* Progress in sidebar */
.mini-prog { margin: 8px 0; }
.mini-prog .bar-wrap { background: #1a2332; border-radius: 4px; height: 6px; overflow: hidden; }
.mini-prog .bar-fill { background: #39bae6; height: 100%; transition: width 0.4s; border-radius: 4px; }
.mini-prog .bar-label { font-size: 10px; color: #546e7a; margin-top: 3px; }

/* Right side */
.right { display: flex; flex-direction: column; }

/* Big progress bar */
.prog { background: #0f1923; padding: 14px 20px; border-bottom: 1px solid #1a2332; }
.prog-bar { background: #1a2332; border-radius: 6px; height: 22px; overflow: hidden; position: relative; }
.prog-fill { background: linear-gradient(90deg, #00695c, #00897b); height: 100%; transition: width 0.5s; border-radius: 6px; }
.prog-txt { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,0.5); }
.stats { display: flex; gap: 20px; margin-top: 6px; font-size: 11px; color: #546e7a; flex-wrap: wrap; }
.stats b { color: #39bae6; font-weight: 600; }

/* Map grid */
.map-area { flex: 1; padding: 16px 20px; overflow: auto; display: flex; flex-direction: column; align-items: center; }
.map-area h3 { font-size: 11px; color: #546e7a; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 10px; }
.grid { display: grid; grid-template-columns: repeat(16, 1fr); gap: 2px; width: 100%; max-width: 560px; }
.gc { aspect-ratio: 1; border-radius: 2px; font-size: 7px; display: flex; align-items: center; justify-content: center; cursor: default; position: relative; font-weight: 600; font-family: 'SF Mono', monospace; }
.gc.e { background: #0d1219; }
.gc.p { background: #1a2332; color: #3d5a6e; }
.gc.s { background: #0d47a1; color: #90caf9; animation: glow 2s ease-in-out infinite; }
.gc.c { background: #1b5e20; color: #a5d6a7; }
.gc.err { background: #b71c1c; color: #ef9a9a; }
@keyframes glow { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
.gc .tip { display: none; position: absolute; bottom: calc(100% + 4px); left: 50%; transform: translateX(-50%); background: #1a2332; color: #bfccd6; padding: 3px 7px; border-radius: 4px; font-size: 9px; white-space: nowrap; z-index: 100; pointer-events: none; border: 1px solid #253545; }
.gc:hover .tip { display: block; }

/* Workers — compact */
.wk-area { background: #0f1923; border-top: 1px solid #1a2332; max-height: 220px; overflow-y: auto; }
.wk-area h3 { font-size: 11px; color: #546e7a; text-transform: uppercase; letter-spacing: 1px; padding: 10px 20px 6px; position: sticky; top: 0; background: #0f1923; z-index: 1; }
.wk-summary { padding: 0 20px 8px; font-size: 11px; color: #546e7a; display: flex; gap: 16px; flex-wrap: wrap; }
.wk-summary b { font-weight: 600; }
.wk-summary .ok { color: #69f0ae; }
.wk-summary .err { color: #ef9a9a; }
.wk-summary .conn { color: #90caf9; }
.wk-tbl { width: 100%; border-collapse: collapse; font-size: 10px; font-family: 'SF Mono', monospace; }
.wk-tbl th { text-align: left; padding: 3px 10px; color: #3d5a6e; font-weight: 500; border-bottom: 1px solid #1a2332; position: sticky; top: 30px; background: #0f1923; }
.wk-tbl td { padding: 3px 10px; border-bottom: 1px solid #0d1219; }
.wk-tbl tr:hover td { background: #0d1219; }
.st { padding: 1px 6px; border-radius: 8px; font-size: 9px; font-weight: 700; text-transform: uppercase; }
.st.idle { background: #1a2332; color: #546e7a; }
.st.connecting { background: #0d47a1; color: #90caf9; }
.st.scanning { background: #1b5e20; color: #69f0ae; }
.st.error { background: #b71c1c; color: #ef9a9a; }
.st.stopped { background: #1a2332; color: #3d5a6e; }

/* Log */
.log { background: #080b10; border-top: 1px solid #1a2332; max-height: 160px; overflow-y: auto; padding: 8px 20px; }
.log h3 { font-size: 11px; color: #546e7a; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; position: sticky; top: 0; background: #080b10; }
.le { font-size: 10px; padding: 1px 0; display: flex; gap: 8px; font-family: 'SF Mono', monospace; }
.le .t { color: #3d5a6e; min-width: 60px; }
.le .m { color: #546e7a; }
.le .m.error { color: #ef9a9a; }
.le .m.warn { color: #ffcc80; }
.le .m.info { color: #546e7a; }
</style>
</head>
<body>

<div class="hdr">
  <h1>L2 Terrain Scanner</h1>
  <span class="tag idle" id="tag">IDLE</span>
  <span class="clock" id="clock"></span>
</div>

<div class="main">
  <!-- Sidebar -->
  <div class="side">
    <!-- Step 1: Setup -->
    <div class="card">
      <h3><span class="step-num">1</span> Setup Accounts</h3>
      <div class="fg">
        <label>Agents to create</label>
        <input type="number" id="bsNum" value="20" min="1" max="200" />
      </div>
      <div class="fg">
        <label>Prefix</label>
        <input type="text" id="bsPrefix" value="scanner" />
      </div>
      <div class="fg">
        <label>Password</label>
        <input type="text" id="bsPassword" value="scanner" />
      </div>
      <div class="row" style="margin-bottom:4px">
        <div class="fg" style="flex:1">
          <label>DB Name</label>
          <input type="text" id="bsDb" value="l2jmobiusc6" />
        </div>
        <div class="fg" style="flex:1">
          <label>DB User</label>
          <input type="text" id="bsDbUser" value="root" />
        </div>
      </div>
      <button class="btn-go" onclick="runBootstrap()" id="btnBoot" style="width:100%">
        Create Accounts + Promote GM
      </button>
      <div class="mini-prog" id="bootProg" style="display:none">
        <div class="bar-wrap"><div class="bar-fill" id="bootBar" style="width:0%"></div></div>
        <div class="bar-label" id="bootLabel">0 / 0</div>
      </div>
    </div>

    <!-- Step 2: Scan -->
    <div class="card">
      <h3><span class="step-num">2</span> Scan Terrain</h3>
      <div class="fg">
        <label>Workers</label>
        <input type="number" id="numWorkers" value="20" min="1" max="200" />
      </div>
      <div class="fg">
        <label>Scan Mode</label>
        <select id="scanMode">
          <option value="block">Block (step=8) — fast</option>
          <option value="cell">Cell (step=1) — detailed</option>
        </select>
      </div>
      <div class="row">
        <button class="btn-green" onclick="startScan()" id="btnStart" style="flex:1">Start Scan</button>
        <button class="btn-red" onclick="stopScan()" id="btnStop" style="flex:1">Stop</button>
      </div>
    </div>

    <!-- Workers +/- -->
    <div class="card">
      <h3>Live Workers</h3>
      <div class="row">
        <button class="btn-sec" onclick="addWorker()" style="flex:1">+ Add</button>
        <button class="btn-sec" onclick="removeWorker()" style="flex:1">- Remove</button>
      </div>
    </div>

    <!-- Server config -->
    <div class="card">
      <h3>Server</h3>
      <div class="row" style="margin-bottom:4px">
        <div class="fg" style="flex:2">
          <label>Login Host</label>
          <input type="text" id="srvHost" value="127.0.0.1" />
        </div>
        <div class="fg" style="flex:1">
          <label>Port</label>
          <input type="number" id="srvPort" value="2106" />
        </div>
      </div>
    </div>

    <!-- Danger zone -->
    <div class="card" style="border-color: #b71c1c33;">
      <h3 style="color:#ef5350">Danger</h3>
      <button class="btn-red" onclick="resetAll()" style="width:100%; font-size:10px">Reset All Progress</button>
    </div>
  </div>

  <!-- Right content -->
  <div class="right">
    <!-- Progress bar -->
    <div class="prog">
      <div class="prog-bar">
        <div class="prog-fill" id="pBar" style="width:0%"></div>
        <div class="prog-txt" id="pTxt">0%</div>
      </div>
      <div class="stats">
        <span>Cells <b id="sCells">0 / 0</b></span>
        <span>Regions <b id="sRegs">0 / 0</b></span>
        <span>Speed <b id="sSpeed">0/s</b></span>
        <span>ETA <b id="sEta">--</b></span>
        <span>Workers <b id="sWk">0</b></span>
        <span>Mode <b id="sMode">block</b></span>
      </div>
    </div>

    <!-- Map -->
    <div class="map-area">
      <h3>Region Map</h3>
      <div class="grid" id="grid"></div>
    </div>

    <!-- Workers -->
    <div class="wk-area" id="wkArea">
      <h3>Workers <span id="wkCount" style="color:#39bae6"></span></h3>
      <div class="wk-summary" id="wkSummary"></div>
      <table class="wk-tbl" id="wkTbl" style="display:none">
        <thead><tr><th>Name</th><th>Status</th><th>Region</th><th>Pos</th><th>c/s</th><th>Total</th><th>Err</th></tr></thead>
        <tbody id="wkBody"></tbody>
      </table>
    </div>

    <!-- Log -->
    <div class="log" id="logBox">
      <h3>Log</h3>
      <div id="logEntries"></div>
    </div>
  </div>
</div>

<script>
const MRX=11,XRX=26,MRY=10,XRY=25;
let RD={},WD={},ES=null;

// Build grid
function buildGrid(){
  const g=document.getElementById('grid');g.innerHTML='';
  for(let y=MRY;y<=XRY;y++)for(let x=MRX;x<=XRX;x++){
    const c=document.createElement('div');
    c.className='gc e';c.id=`r${x}_${y}`;
    c.innerHTML=`<span class="tip">${x}_${y}</span>`;
    g.appendChild(c);
  }
}

function updCell(k,st){
  const el=document.getElementById('r'+k);if(!el)return;
  const cls={pending:'p',scanning:'s',complete:'c',error:'err'}[st]||'e';
  el.className='gc '+cls;
  const r=RD[k];
  if(r){
    const p=Math.round(r.progress*100);
    const tip=`${k} (${st}${p>0?' '+p+'%':''})`;
    if(st==='scanning'&&p>0){el.innerHTML=p+`<span class="tip">${tip}</span>`;}
    else{el.innerHTML=`<span class="tip">${tip}</span>`;}
  }
}

function fetchStatus(){
  fetch('/api/status').then(r=>r.json()).then(d=>{RD=d.regions||{};WD=d.workers||{};updUI(d);}).catch(()=>{});
}

function updUI(d){
  // Progress
  const p=Math.round((d.progress||0)*1000)/10;
  document.getElementById('pBar').style.width=p+'%';
  document.getElementById('pTxt').textContent=p.toFixed(1)+'%';
  document.getElementById('sCells').textContent=(d.scanned_cells||0).toLocaleString()+' / '+(d.total_cells||0).toLocaleString();
  document.getElementById('sRegs').textContent=(d.complete_regions||0)+' / '+(d.total_regions||0);
  document.getElementById('sSpeed').textContent=(d.total_speed||0)+'/s';
  document.getElementById('sWk').textContent=d.num_workers||0;
  document.getElementById('sMode').textContent=d.scan_mode||'block';

  const eta=d.eta_seconds||0;
  if(eta>0){const h=Math.floor(eta/3600),m=Math.floor((eta%3600)/60);
    document.getElementById('sEta').textContent=h>0?h+'h '+m+'m':m+'m';
  }else{document.getElementById('sEta').textContent='--';}

  // Tag
  const tag=document.getElementById('tag');
  if(d.bootstrap_running){tag.textContent='SETUP';tag.className='tag boot';}
  else if(d.running&&d.scanning_regions>0){tag.textContent='SCANNING';tag.className='tag run';}
  else if(d.running){tag.textContent='RUNNING';tag.className='tag run';}
  else{tag.textContent='IDLE';tag.className='tag idle';}

  // Grid
  for(const[k,r]of Object.entries(RD))updCell(k,r.status);

  // Workers
  const ws=Object.values(WD);
  document.getElementById('wkCount').textContent=ws.length>0?'('+ws.length+')':'';

  if(ws.length===0){
    document.getElementById('wkSummary').innerHTML='<span>No workers</span>';
    document.getElementById('wkTbl').style.display='none';
  }else{
    // Summary counts
    const counts={scanning:0,connecting:0,idle:0,error:0,stopped:0};
    ws.forEach(w=>{counts[w.status]=(counts[w.status]||0)+1;});
    let parts=[];
    if(counts.scanning)parts.push(`<b class="ok">${counts.scanning}</b> scanning`);
    if(counts.connecting)parts.push(`<b class="conn">${counts.connecting}</b> connecting`);
    if(counts.idle)parts.push(`<b>${counts.idle}</b> idle`);
    if(counts.error)parts.push(`<b class="err">${counts.error}</b> error`);
    if(counts.stopped)parts.push(`<b>${counts.stopped}</b> stopped`);
    document.getElementById('wkSummary').innerHTML=parts.join(' &middot; ');

    // Table — show up to 50, summarize rest
    const shown=ws.slice(0,50);
    document.getElementById('wkTbl').style.display='table';
    document.getElementById('wkBody').innerHTML=shown.map(w=>`<tr>
      <td>${esc(w.name)}</td>
      <td><span class="st ${w.status}">${w.status}</span></td>
      <td>${w.current_region||'-'}</td>
      <td>${w.x},${w.y}</td>
      <td>${w.cells_per_sec}</td>
      <td>${(w.cells_scanned||0).toLocaleString()}</td>
      <td>${w.errors||0}</td>
    </tr>`).join('')+(ws.length>50?`<tr><td colspan="7" style="color:#3d5a6e;text-align:center">...and ${ws.length-50} more</td></tr>`:'');
  }
}

function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML;}

// SSE
function connectSSE(){
  if(ES)ES.close();
  ES=new EventSource('/api/events');
  ES.addEventListener('worker_update',e=>{
    const ev=JSON.parse(e.data),d=ev.data;
    if(d.status==='removed')delete WD[d.worker];
    else if(WD[d.worker])Object.assign(WD[d.worker],d);
    else WD[d.worker]={name:d.worker,status:d.status||'idle',current_region:'',x:0,y:0,z:0,cells_scanned:0,cells_per_sec:0,errors:0,...d};
    schedRefresh();
  });
  ES.addEventListener('region_update',e=>{
    const d=JSON.parse(e.data).data;
    if(RD[d.region])RD[d.region].status=d.status;
    updCell(d.region,d.status);
  });
  ES.addEventListener('progress_update',()=>schedRefresh());
  ES.addEventListener('log',e=>{
    const d=JSON.parse(e.data).data;addLog(d.message,d.level);
  });
  ES.addEventListener('bootstrap_progress',e=>{
    const d=JSON.parse(e.data).data;updBootstrap(d);
  });
  ES.onerror=()=>setTimeout(connectSSE,3000);
}

let _rt=null;
function schedRefresh(){if(!_rt)_rt=setTimeout(()=>{_rt=null;fetchStatus();},1000);}

// Bootstrap progress
function updBootstrap(d){
  const prog=document.getElementById('bootProg');
  const bar=document.getElementById('bootBar');
  const lbl=document.getElementById('bootLabel');
  const btn=document.getElementById('btnBoot');

  if(d.phase==='done'){
    prog.style.display='none';
    btn.disabled=false;
    btn.textContent='Create Accounts + Promote GM';
    addLog(`Setup complete: ${d.created} created, ${d.failed} failed, ${d.promoted} promoted to GM`,'info');
  }else{
    prog.style.display='block';
    const pct=d.total>0?Math.round(d.current/d.total*100):0;
    bar.style.width=pct+'%';
    lbl.textContent=`${d.current} / ${d.total} (${d.created} OK, ${d.failed} fail)`;
  }
}

// Log
function addLog(msg,level){
  const c=document.getElementById('logEntries');
  const t=new Date().toLocaleTimeString('en-US',{hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});
  const e=document.createElement('div');e.className='le';
  e.innerHTML=`<span class="t">${t}</span><span class="m ${level||'info'}">${esc(msg)}</span>`;
  c.appendChild(e);
  while(c.children.length>300)c.removeChild(c.firstChild);
  document.getElementById('logBox').scrollTop=999999;
}

// Shared config getters
function cfg(){
  return {
    login_host:document.getElementById('srvHost').value,
    login_port:parseInt(document.getElementById('srvPort').value)||2106,
    prefix:document.getElementById('bsPrefix').value||'scanner',
    password:document.getElementById('bsPassword').value||'scanner',
  };
}

// Actions
function runBootstrap(){
  const num=parseInt(document.getElementById('bsNum').value)||20;
  const btn=document.getElementById('btnBoot');
  btn.disabled=true;btn.textContent='Setting up...';
  document.getElementById('bootProg').style.display='block';
  document.getElementById('bootBar').style.width='0%';
  document.getElementById('bootLabel').textContent='Starting...';

  fetch('/api/bootstrap',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({num,promote:true,
      db_name:document.getElementById('bsDb').value,
      db_user:document.getElementById('bsDbUser').value,
      ...cfg()})
  }).then(r=>r.json()).then(d=>{
    addLog(`Bootstrap started: ${d.num} accounts`,'info');
  });
}

function startScan(){
  const n=parseInt(document.getElementById('numWorkers').value)||20;
  const mode=document.getElementById('scanMode').value;
  fetch('/api/scan/start',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({num_workers:n,scan_mode:mode,...cfg()})
  }).then(r=>r.json()).then(d=>{
    addLog(`Scan started: ${d.num_workers} workers, mode=${d.scan_mode}`,'info');
    setTimeout(fetchStatus,2000);
  });
}

function stopScan(){
  fetch('/api/scan/stop',{method:'POST'}).then(r=>r.json()).then(()=>addLog('Stop requested','warn'));
}

function addWorker(){
  fetch('/api/worker/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})
  }).then(r=>r.json()).then(()=>{addLog('Worker added','info');setTimeout(fetchStatus,1000);});
}

function removeWorker(){
  fetch('/api/worker/remove',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})
  }).then(r=>r.json()).then(()=>{addLog('Worker removed','warn');setTimeout(fetchStatus,1000);});
}

function resetAll(){
  if(!confirm('Reset ALL scan progress? This cannot be undone.'))return;
  fetch('/api/scan/reset',{method:'POST'}).then(r=>r.json()).then(()=>{
    addLog('Progress reset','warn');RD={};buildGrid();fetchStatus();
  });
}

// Sync worker count input with bootstrap count
document.getElementById('bsNum').addEventListener('change',function(){
  document.getElementById('numWorkers').value=this.value;
});

// Clock
function tick(){document.getElementById('clock').textContent=new Date().toLocaleTimeString('en-US',{hour12:false});}

// Init
buildGrid();fetchStatus();connectSSE();
setInterval(tick,1000);setInterval(fetchStatus,10000);tick();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="L2 Terrain Scanner — All-in-One Dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard bind host")
    parser.add_argument("--port", type=int, default=5556, help="Dashboard port")
    parser.add_argument("--login-host", default="127.0.0.1", help="L2 login server host")
    parser.add_argument("--login-port", type=int, default=2106, help="L2 login server port")
    args = parser.parse_args()

    manager.login_host = args.login_host
    manager.login_port = args.login_port

    print(f"Dashboard: http://{args.host}:{args.port}")
    print(f"L2 Server: {args.login_host}:{args.login_port}")
    print()
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
