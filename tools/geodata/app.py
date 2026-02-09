#!/usr/bin/env python3
"""
L2J Geodata Editor — Web UI
Run: python3 app.py
Open: http://localhost:5555
"""
from __future__ import annotations

import io
import json
import os
import base64
from pathlib import Path

from flask import Flask, render_template_string, request, jsonify, send_file

import sys
sys.path.insert(0, str(Path(__file__).parent))

from l2d_parser import (
    parse_l2d, write_l2d, GeoRegion,
    BlockFlat, BlockComplex, BlockMultilayer,
    region_to_world_coords, world_to_region_coords,
    REGION_CELLS_X, REGION_CELLS_Y, REGION_BLOCKS_X, REGION_BLOCKS_Y,
    BLOCK_CELLS_X, BLOCK_CELLS_Y, NSWE_ALL, NSWE_ALL_L2D,
    FLAG_N, FLAG_S, FLAG_E, FLAG_W,
)
from renderer import (
    render_heightmap, render_nswe, render_combined,
    render_block_types, render_cell_detail,
    extract_height_grid, extract_nswe_grid, extract_layer_count_grid,
)

app = Flask(__name__)

GEODATA_DIR = os.environ.get(
    "GEODATA_DIR",
    str(Path(__file__).parent.parent.parent / "dist" / "game" / "data" / "geodata")
)

# Cache loaded regions
_region_cache: dict[str, GeoRegion] = {}


def get_region(filename: str) -> GeoRegion:
    if filename not in _region_cache:
        filepath = Path(GEODATA_DIR) / filename
        _region_cache[filename] = parse_l2d(filepath)
    return _region_cache[filename]


def clear_cache(filename: str):
    _region_cache.pop(filename, None)


def img_to_base64(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/regions")
def api_regions():
    gdir = Path(GEODATA_DIR)
    files = sorted(f.name for f in gdir.glob("*.l2d"))
    return jsonify(files)


@app.route("/api/region/<filename>/info")
def api_region_info(filename):
    region = get_region(filename)
    stats = region.stats
    return jsonify(stats)


@app.route("/api/region/<filename>/render")
def api_region_render(filename):
    mode = request.args.get("mode", "combined")
    region = get_region(filename)

    if mode == "heightmap":
        img = render_heightmap(region)
    elif mode == "nswe":
        img = render_nswe(region)
    elif mode == "blocks":
        img = render_block_types(region)
    else:
        img = render_combined(region)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/api/region/<filename>/cell")
def api_cell_info(filename):
    cx = int(request.args["cx"])
    cy = int(request.args["cy"])
    region = get_region(filename)
    layers = region.get_layers(cx, cy)
    wx, wy = region_to_world_coords(region.region_x, region.region_y, cx, cy)

    bx = cx // BLOCK_CELLS_X
    by = cy // BLOCK_CELLS_Y
    block = region.get_block(bx, by)
    block_type = type(block).__name__

    return jsonify({
        "cell_x": cx,
        "cell_y": cy,
        "world_x": wx,
        "world_y": wy,
        "block_type": block_type,
        "block_x": bx,
        "block_y": by,
        "layers": [
            {
                "index": i,
                "height": cell.height,
                "nswe": cell.nswe,
                "nswe_hex": f"0x{cell.nswe:02X}",
                "nswe_str": cell.nswe_str(),
                "walkable": cell.is_fully_walkable,
                "blocked": cell.is_blocked,
            }
            for i, cell in enumerate(layers)
        ],
    })


@app.route("/api/region/<filename>/detail")
def api_cell_detail(filename):
    cx = int(request.args["cx"])
    cy = int(request.args["cy"])
    radius = int(request.args.get("radius", 16))
    region = get_region(filename)
    img = render_cell_detail(region, cx, cy, radius=radius, cell_size=20)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/api/region/<filename>/edit", methods=["POST"])
def api_edit_cell(filename):
    data = request.json
    cx = int(data["cx"])
    cy = int(data["cy"])
    layer = int(data.get("layer", 0))

    region = get_region(filename)
    bx = cx // BLOCK_CELLS_X
    by = cy // BLOCK_CELLS_Y
    lx = cx % BLOCK_CELLS_X
    ly = cy % BLOCK_CELLS_Y
    block = region.get_block(bx, by)

    old_cell = block.get_cell(lx, ly, layer)
    new_height = int(data["height"]) if "height" in data else old_cell.height
    new_nswe = int(data["nswe"]) if "nswe" in data else old_cell.nswe

    if isinstance(block, BlockFlat):
        block.height = new_height
    elif isinstance(block, BlockComplex):
        block.set_cell(lx, ly, new_height, new_nswe)
    elif isinstance(block, BlockMultilayer):
        block.set_cell(lx, ly, layer, new_height, new_nswe)

    return jsonify({"status": "ok", "height": new_height, "nswe": new_nswe})


@app.route("/api/region/<filename>/unblock", methods=["POST"])
def api_unblock(filename):
    data = request.json
    cx = int(data["cx"])
    cy = int(data["cy"])
    radius = int(data.get("radius", 3))

    region = get_region(filename)
    count = 0

    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            x, y = cx + dx, cy + dy
            if x < 0 or y < 0 or x >= REGION_CELLS_X or y >= REGION_CELLS_Y:
                continue
            bx = x // BLOCK_CELLS_X
            by = y // BLOCK_CELLS_Y
            lx = x % BLOCK_CELLS_X
            ly = y % BLOCK_CELLS_Y
            block = region.get_block(bx, by)

            if isinstance(block, BlockFlat):
                continue
            elif isinstance(block, BlockComplex):
                old = block.get_cell(lx, ly)
                if (old.nswe & NSWE_ALL) != NSWE_ALL:
                    block.set_cell(lx, ly, old.height, NSWE_ALL_L2D)
                    count += 1
            elif isinstance(block, BlockMultilayer):
                for li, cell in enumerate(block.get_layers(lx, ly)):
                    if (cell.nswe & NSWE_ALL) != NSWE_ALL:
                        block.set_cell(lx, ly, li, cell.height, NSWE_ALL_L2D)
                        count += 1

    return jsonify({"status": "ok", "unblocked": count})


@app.route("/api/region/<filename>/save", methods=["POST"])
def api_save(filename):
    region = get_region(filename)
    filepath = Path(GEODATA_DIR) / filename
    write_l2d(region, filepath)
    clear_cache(filename)
    return jsonify({"status": "saved", "file": str(filepath)})


@app.route("/api/world2geo")
def api_world2geo():
    wx = int(request.args["x"])
    wy = int(request.args["y"])
    rx, ry, cx, cy = world_to_region_coords(wx, wy)
    return jsonify({"region_x": rx, "region_y": ry, "cell_x": cx, "cell_y": cy, "file": f"{rx}_{ry}.l2d"})


HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>L2J Geodata Editor</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; display: flex; height: 100vh; }

/* Sidebar */
.sidebar { width: 320px; background: #16213e; padding: 16px; overflow-y: auto; border-right: 1px solid #0f3460; display: flex; flex-direction: column; gap: 12px; }
.sidebar h1 { font-size: 18px; color: #e94560; margin-bottom: 4px; }
.sidebar h2 { font-size: 14px; color: #888; font-weight: normal; }
.sidebar h3 { font-size: 13px; color: #e94560; margin-top: 8px; border-bottom: 1px solid #0f3460; padding-bottom: 4px; }

/* Controls */
select, input, button { font-family: inherit; font-size: 13px; padding: 6px 10px; border-radius: 4px; border: 1px solid #0f3460; background: #1a1a2e; color: #e0e0e0; outline: none; }
select:hover, input:hover { border-color: #e94560; }
button { background: #e94560; border: none; color: white; cursor: pointer; font-weight: 600; }
button:hover { background: #c73450; }
button.secondary { background: #0f3460; }
button.secondary:hover { background: #1a4a8a; }
button.save-btn { background: #27ae60; }
button.save-btn:hover { background: #219a52; }
.btn-row { display: flex; gap: 6px; }
.btn-row button { flex: 1; }
label { font-size: 12px; color: #888; display: block; margin-bottom: 2px; }
.field { margin-bottom: 8px; }
.field input, .field select { width: 100%; }

/* Cell info */
.cell-info { background: #1a1a2e; border-radius: 6px; padding: 10px; font-size: 12px; line-height: 1.8; }
.cell-info .val { color: #4fc3f7; font-weight: 600; }
.cell-info .blocked { color: #e94560; }
.cell-info .walkable { color: #66bb6a; }

/* NSWE grid */
.nswe-grid { display: grid; grid-template-columns: repeat(3, 32px); gap: 2px; justify-content: center; margin: 8px 0; }
.nswe-btn { width: 32px; height: 32px; font-size: 11px; font-weight: 700; border-radius: 4px; display: flex; align-items: center; justify-content: center; cursor: pointer; transition: all 0.15s; }
.nswe-btn.active { background: #66bb6a; color: #1a1a2e; }
.nswe-btn.inactive { background: #333; color: #666; }
.nswe-btn.empty { visibility: hidden; }

/* Main area */
.main { flex: 1; display: flex; flex-direction: column; }
.toolbar { background: #16213e; padding: 8px 16px; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid #0f3460; }
.toolbar .mode-btn { padding: 4px 12px; font-size: 12px; border-radius: 12px; background: #1a1a2e; border: 1px solid #0f3460; color: #888; cursor: pointer; }
.toolbar .mode-btn.active { background: #e94560; color: white; border-color: #e94560; }
.coords { font-size: 12px; color: #666; margin-left: auto; }

/* Map */
.map-container { flex: 1; overflow: auto; position: relative; display: flex; align-items: center; justify-content: center; background: #111; }
.map-container img { cursor: crosshair; image-rendering: pixelated; }

/* Detail panel */
.detail-panel { display: none; position: absolute; right: 16px; top: 16px; background: rgba(22, 33, 62, 0.95); border: 1px solid #0f3460; border-radius: 8px; padding: 8px; }
.detail-panel img { image-rendering: pixelated; border-radius: 4px; }

/* Status bar */
.statusbar { background: #16213e; padding: 6px 16px; font-size: 12px; color: #666; border-top: 1px solid #0f3460; display: flex; gap: 20px; }
.statusbar .status-item { }
.statusbar .status-val { color: #4fc3f7; }

/* World coord lookup */
.world-lookup { display: flex; gap: 4px; }
.world-lookup input { width: 80px; }
.world-lookup button { padding: 4px 8px; font-size: 11px; }
</style>
</head>
<body>

<div class="sidebar">
  <div>
    <h1>L2J Geodata Editor</h1>
    <h2>Interlude Map Viewer</h2>
  </div>

  <div class="field">
    <label>Region File</label>
    <select id="regionSelect" onchange="loadRegion()">
      <option value="">Select a region...</option>
    </select>
  </div>

  <div id="regionInfo" style="display:none">
    <h3>Region Stats</h3>
    <div class="cell-info" id="statsBox"></div>
  </div>

  <div id="cellPanel" style="display:none">
    <h3>Selected Cell</h3>
    <div class="cell-info" id="cellBox"></div>

    <h3>Movement Flags</h3>
    <div class="nswe-grid" id="nsweGrid">
      <div class="nswe-btn empty"></div>
      <div class="nswe-btn inactive" data-dir="N" data-flag="8" onclick="toggleNswe(this)">N</div>
      <div class="nswe-btn empty"></div>
      <div class="nswe-btn inactive" data-dir="W" data-flag="2" onclick="toggleNswe(this)">W</div>
      <div class="nswe-btn inactive" style="font-size:9px; background:#222; cursor:default">+</div>
      <div class="nswe-btn inactive" data-dir="E" data-flag="1" onclick="toggleNswe(this)">E</div>
      <div class="nswe-btn empty"></div>
      <div class="nswe-btn inactive" data-dir="S" data-flag="4" onclick="toggleNswe(this)">S</div>
      <div class="nswe-btn empty"></div>
    </div>

    <div class="field">
      <label>Height</label>
      <input type="number" id="editHeight" />
    </div>

    <div class="btn-row">
      <button onclick="applyEdit()">Apply Edit</button>
      <button class="secondary" onclick="makeWalkable()">Walkable</button>
    </div>

    <h3>Area Tools</h3>
    <div class="field">
      <label>Unblock Radius</label>
      <input type="number" id="unblockRadius" value="3" min="0" max="50" />
    </div>
    <button class="secondary" onclick="unblockArea()" style="width:100%">Unblock Area</button>

    <div style="margin-top:12px">
      <button class="save-btn" onclick="saveRegion()" style="width:100%">Save to Disk</button>
    </div>
  </div>

  <div>
    <h3>World Coordinates</h3>
    <div class="world-lookup">
      <input type="number" id="worldX" placeholder="X" />
      <input type="number" id="worldY" placeholder="Y" />
      <button onclick="lookupWorld()">Go</button>
    </div>
  </div>
</div>

<div class="main">
  <div class="toolbar">
    <span class="mode-btn active" data-mode="combined" onclick="setMode(this)">Combined</span>
    <span class="mode-btn" data-mode="heightmap" onclick="setMode(this)">Height</span>
    <span class="mode-btn" data-mode="nswe" onclick="setMode(this)">Movement</span>
    <span class="mode-btn" data-mode="blocks" onclick="setMode(this)">Block Types</span>
    <span class="coords" id="hoverCoords">Hover over map</span>
  </div>

  <div class="map-container" id="mapContainer">
    <img id="mapImg" style="display:none" />
    <div class="detail-panel" id="detailPanel">
      <img id="detailImg" width="330" height="330" />
    </div>
    <div id="emptyState" style="color:#444; font-size:14px;">Select a region to view</div>
  </div>

  <div class="statusbar">
    <span class="status-item">Zoom: <span class="status-val" id="zoomLevel">100%</span></span>
    <span class="status-item">Cells: <span class="status-val">2048 x 2048</span></span>
    <span class="status-item" id="statusMsg"></span>
  </div>
</div>

<script>
let currentFile = null;
let currentMode = 'combined';
let selectedCx = -1, selectedCy = -1;
let zoom = 0.5;
const mapImg = document.getElementById('mapImg');
const mapContainer = document.getElementById('mapContainer');

// Load region list
fetch('/api/regions').then(r => r.json()).then(files => {
  const sel = document.getElementById('regionSelect');
  files.forEach(f => {
    const opt = document.createElement('option');
    opt.value = f; opt.textContent = f.replace('.l2d','');
    sel.appendChild(opt);
  });
});

function loadRegion() {
  const file = document.getElementById('regionSelect').value;
  if (!file) return;
  currentFile = file;
  document.getElementById('emptyState').style.display = 'none';

  // Load info
  fetch(`/api/region/${file}/info`).then(r => r.json()).then(info => {
    document.getElementById('regionInfo').style.display = 'block';
    document.getElementById('statsBox').innerHTML = `
      Region: <span class="val">${info.region}</span><br>
      Flat: <span class="val">${info.flat_blocks.toLocaleString()}</span> |
      Complex: <span class="val">${info.complex_blocks.toLocaleString()}</span> |
      Multi: <span class="val">${info.multilayer_blocks.toLocaleString()}</span>
    `;
  });

  // Load map
  setStatus('Loading map...');
  mapImg.onload = () => {
    mapImg.style.display = 'block';
    applyZoom();
    setStatus('Ready');
  };
  mapImg.src = `/api/region/${file}/render?mode=${currentMode}&t=${Date.now()}`;
}

function setMode(el) {
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
  el.classList.add('active');
  currentMode = el.dataset.mode;
  if (currentFile) {
    setStatus('Rendering...');
    mapImg.src = `/api/region/${currentFile}/render?mode=${currentMode}&t=${Date.now()}`;
  }
}

function applyZoom() {
  mapImg.style.width = (2048 * zoom) + 'px';
  mapImg.style.height = (2048 * zoom) + 'px';
  document.getElementById('zoomLevel').textContent = Math.round(zoom * 100) + '%';
}

// Mouse events
mapImg.addEventListener('mousemove', (e) => {
  const rect = mapImg.getBoundingClientRect();
  const cx = Math.floor((e.clientX - rect.left) / rect.width * 2048);
  const cy = Math.floor((e.clientY - rect.top) / rect.height * 2048);
  if (cx >= 0 && cx < 2048 && cy >= 0 && cy < 2048) {
    document.getElementById('hoverCoords').textContent = `Cell: (${cx}, ${cy})`;
  }
});

mapImg.addEventListener('click', (e) => {
  const rect = mapImg.getBoundingClientRect();
  const cx = Math.floor((e.clientX - rect.left) / rect.width * 2048);
  const cy = Math.floor((e.clientY - rect.top) / rect.height * 2048);
  if (cx >= 0 && cx < 2048 && cy >= 0 && cy < 2048) {
    selectCell(cx, cy);
  }
});

// Zoom with scroll
mapContainer.addEventListener('wheel', (e) => {
  e.preventDefault();
  if (e.deltaY < 0) zoom = Math.min(zoom * 1.2, 4);
  else zoom = Math.max(zoom / 1.2, 0.2);
  applyZoom();
}, { passive: false });

function selectCell(cx, cy) {
  if (!currentFile) return;
  selectedCx = cx; selectedCy = cy;

  fetch(`/api/region/${currentFile}/cell?cx=${cx}&cy=${cy}`).then(r => r.json()).then(data => {
    document.getElementById('cellPanel').style.display = 'block';
    const layer = data.layers[0];

    document.getElementById('cellBox').innerHTML = `
      Cell: <span class="val">(${data.cell_x}, ${data.cell_y})</span><br>
      World: <span class="val">(${data.world_x}, ${data.world_y})</span><br>
      Block: <span class="val">${data.block_type} (${data.block_x}, ${data.block_y})</span><br>
      Height: <span class="val">${layer.height}</span><br>
      NSWE: <span class="val">${layer.nswe_hex}</span> (${layer.nswe_str})<br>
      Layers: <span class="val">${data.layers.length}</span><br>
      Status: <span class="${layer.walkable ? 'walkable' : 'blocked'}">${layer.walkable ? 'WALKABLE' : layer.blocked ? 'BLOCKED' : 'PARTIAL'}</span>
    `;

    document.getElementById('editHeight').value = layer.height;

    // Update NSWE buttons
    const nswe = layer.nswe;
    document.querySelectorAll('.nswe-btn[data-flag]').forEach(btn => {
      const flag = parseInt(btn.dataset.flag);
      if (nswe & flag) {
        btn.className = 'nswe-btn active';
      } else {
        btn.className = 'nswe-btn inactive';
      }
    });
  });

  // Load detail view
  const dp = document.getElementById('detailPanel');
  dp.style.display = 'block';
  document.getElementById('detailImg').src = `/api/region/${currentFile}/detail?cx=${cx}&cy=${cy}&radius=8&t=${Date.now()}`;
}

function toggleNswe(btn) {
  if (btn.classList.contains('active')) {
    btn.className = 'nswe-btn inactive';
  } else {
    btn.className = 'nswe-btn active';
  }
}

function getNsweFromGrid() {
  let nswe = 0;
  document.querySelectorAll('.nswe-btn[data-flag]').forEach(btn => {
    if (btn.classList.contains('active')) {
      nswe |= parseInt(btn.dataset.flag);
    }
  });
  // Also set diagonal flags if all adjacent cardinal flags are active
  const n = nswe & 8, s = nswe & 4, e = nswe & 1, w = nswe & 2;
  if (n && e) nswe |= 64;  // NE
  if (n && w) nswe |= 128; // NW
  if (s && e) nswe |= 16;  // SE
  if (s && w) nswe |= 32;  // SW
  return nswe;
}

function applyEdit() {
  if (!currentFile || selectedCx < 0) return;
  const height = parseInt(document.getElementById('editHeight').value);
  const nswe = getNsweFromGrid();

  fetch(`/api/region/${currentFile}/edit`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ cx: selectedCx, cy: selectedCy, height, nswe })
  }).then(r => r.json()).then(() => {
    setStatus('Cell edited (unsaved)');
    selectCell(selectedCx, selectedCy);
  });
}

function makeWalkable() {
  if (!currentFile || selectedCx < 0) return;
  fetch(`/api/region/${currentFile}/edit`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ cx: selectedCx, cy: selectedCy, nswe: 255 })
  }).then(r => r.json()).then(() => {
    setStatus('Cell made walkable (unsaved)');
    selectCell(selectedCx, selectedCy);
  });
}

function unblockArea() {
  if (!currentFile || selectedCx < 0) return;
  const radius = parseInt(document.getElementById('unblockRadius').value);
  fetch(`/api/region/${currentFile}/unblock`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ cx: selectedCx, cy: selectedCy, radius })
  }).then(r => r.json()).then(data => {
    setStatus(`Unblocked ${data.unblocked} cells (unsaved)`);
    selectCell(selectedCx, selectedCy);
  });
}

function saveRegion() {
  if (!currentFile) return;
  if (!confirm('Save changes to disk? This will overwrite the L2D file.')) return;
  fetch(`/api/region/${currentFile}/save`, { method: 'POST' })
    .then(r => r.json()).then(data => {
      setStatus(`Saved: ${data.file}`);
      // Refresh map
      mapImg.src = `/api/region/${currentFile}/render?mode=${currentMode}&t=${Date.now()}`;
    });
}

function lookupWorld() {
  const x = document.getElementById('worldX').value;
  const y = document.getElementById('worldY').value;
  if (!x || !y) return;
  fetch(`/api/world2geo?x=${x}&y=${y}`).then(r => r.json()).then(data => {
    // Switch to that region if available
    const sel = document.getElementById('regionSelect');
    const opt = Array.from(sel.options).find(o => o.value === data.file);
    if (opt) {
      sel.value = data.file;
      loadRegion();
      setTimeout(() => selectCell(data.cell_x, data.cell_y), 2000);
    }
    setStatus(`World (${x},${y}) → Region ${data.file} Cell (${data.cell_x},${data.cell_y})`);
  });
}

function setStatus(msg) {
  document.getElementById('statusMsg').innerHTML = msg;
}
</script>
</body>
</html>
"""

if __name__ == "__main__":
    print(f"Geodata directory: {GEODATA_DIR}")
    print(f"Files found: {len(list(Path(GEODATA_DIR).glob('*.l2d')))}")
    print()
    print("Open http://localhost:5555 in your browser")
    print()
    app.run(host="127.0.0.1", port=5555, debug=False)
