# L2J Interlude Toolkit

### Headless Python Client, Multi-Agent Geodata Scanner & Server Management for Lineage 2 C6 Interlude

A complete developer toolkit for [L2J Mobius C6 Interlude](https://www.l2jmobius.org/) private servers. Connect headless bots, scan terrain at scale, edit geodata visually, and manage your server — all without a Windows game client.

---

## What's Inside

### Headless L2 Client (Python)
A fully functional Lineage 2 game client written in Python. Connects directly to login + game servers, handles the full authentication chain, character creation, and in-game packet communication. No Windows. No game client install. Just Python.

- Full login protocol (BlowfishKey exchange, RSA auth, server selection)
- GameCrypt XOR cipher implementation (encrypt/decrypt game packets)
- Character creation from code (pick class, name, appearance)
- CreatureSay packet parsing for server-to-client communication
- Admin command execution (SendBypassBuildCmd)

### Multi-Agent Terrain Scanner
Deploy up to 20+ headless agents simultaneously to scan the entire game world's terrain data. Each agent runs in its own thread with its own game connection, scanning regions in parallel via custom admin commands that query GeoEngine directly.

- Custom `AdminTerrainScan` server command — batch-queries 256 blocks per request via base64-encoded responses
- `AdminGeoExport` — full-fidelity geodata export using native `ABlock.saveBlock()` (bit-perfect `.l2d` files)
- SQLite persistence — resume interrupted scans
- 139 regions scanned in ~2 minutes with 20 agents

### Web Dashboard (Real-Time)
Flask-based web UI with Server-Sent Events for live progress tracking.

- **World map grid** — 11x16 region grid, color-coded: gray=pending, blue+pulse=scanning, green=complete, red=error
- **Worker table** — per-agent status, current region, cells/sec, error count
- **Controls** — start/stop, dynamic worker count, scan mode selection
- **Event log** — scrolling real-time log

> `http://localhost:5556` — Terrain Scanner Dashboard
> `http://localhost:5555` — Geodata Editor

### Geodata Editor (Web UI)
Visual geodata browser and editor. Renders heightmaps, NSWE walkability maps, block type overlays. Edit individual cells, unblock paths, export renders.

- L2D binary format parser (flat, complex, multilayer blocks)
- Multiple render modes: heightmap, NSWE flags, block types, combined, cell detail
- World coordinate ↔ geo coordinate conversion
- CLI tool for batch operations (`geodata_tool.py`)

### Server Management CLI
One script to rule them all. Start/stop servers, manage accounts, tweak rates, backup databases.

```
./l2j-manage.sh status          # Check if servers are running
./l2j-manage.sh start           # Start login + game server
./l2j-manage.sh set-rates 5     # Set all rates to 5x
./l2j-manage.sh gm admin        # Promote account to GM
./l2j-manage.sh db-backup       # Backup MariaDB
./l2j-manage.sh rebuild         # Recompile Java + copy JARs
```

### Bootstrap Automation
Create N accounts + characters + promote to GM in one command. Uses `AutoCreateAccounts` for account creation and MariaDB for GM promotion.

```bash
# Create 20 scanner accounts with characters, promote all to GM
./terrain-scanner.sh --bootstrap --num 20 --promote
```

---

## Architecture

```
lineage2vzla/
├── java/                          # L2J Mobius C6 server source (Java)
│   └── org/l2jmobius/
│       ├── gameserver/
│       │   ├── geoengine/         # GeoEngine + geodata block types
│       │   │   └── GeoEngine.java #   + exportRegion() for full-fidelity export
│       │   └── handler/
│       │       └── admincommandhandlers/
│       │           ├── AdminTerrainScan.java   # Batch geo queries via packets
│       │           └── AdminGeoExport.java     # Server-side L2D export
│       └── tools/
│           └── geodataconverter/  # L2J/L2OFF → L2D converter
│
├── tools/
│   ├── headless-client/           # Python headless L2 client
│   │   ├── l2_client.py           #   Login + Game client protocol
│   │   ├── l2_crypto.py           #   BlowfishEngine + GameCrypt
│   │   ├── dashboard.py           #   Web dashboard (Flask + SSE)
│   │   ├── scan_worker.py         #   Single agent worker thread
│   │   ├── scan_manager.py        #   Multi-worker orchestrator
│   │   ├── scan_state.py          #   Thread-safe state + SQLite
│   │   ├── bootstrap.py           #   Account/character automation
│   │   └── terrain_scanner.py     #   Single-agent scanner
│   │
│   └── geodata/                   # Geodata processing tools
│       ├── l2d_parser.py          #   L2D binary format parser
│       ├── renderer.py            #   Region rendering (PNG)
│       ├── geodata_tool.py        #   CLI geodata tool
│       └── app.py                 #   Web editor (Flask)
│
├── dist/                          # Server distribution
│   ├── game/                      #   Game server runtime
│   │   ├── data/geodata/          #   L2D geodata files (139 regions)
│   │   └── config/                #   Server configuration
│   └── login/                     #   Login server runtime
│
├── l2j-manage.sh                  # Server management CLI
├── terrain-scanner.sh             # Terrain scanner launcher
├── geodata-editor.sh              # Geodata editor launcher
├── rebuild.sh                     # Java recompile script
└── build.xml                      # Ant build configuration
```

---

## Quick Start

### Prerequisites

- Java JDK 21 (`brew install openjdk@21` on macOS)
- MariaDB (`brew install mariadb`)
- Python 3.10+ with Flask (`pip install flask`)
- Apache Ant (`brew install ant`)

### 1. Database Setup

```bash
brew services start mariadb
./l2j-manage.sh db-reset    # Creates database + imports schemas
```

### 2. Start the Server

```bash
./l2j-manage.sh start       # Starts MariaDB → Login → Game
./l2j-manage.sh status      # Verify everything is running
```

### 3. Launch the Geodata Editor

```bash
./geodata-editor.sh          # Opens http://localhost:5555
```

### 4. Run the Terrain Scanner

```bash
# Bootstrap 20 scanner accounts
./terrain-scanner.sh --bootstrap --num 20 --promote

# Launch the dashboard
./terrain-scanner.sh --dashboard
# Open http://localhost:5556, click "Start Scan"
```

---

## Geodata

The server ships with flat-only geodata (minimal terrain detail). For production-quality geodata with proper walls, cliffs, and multi-layer terrain, you need a community geodata pack.

### Getting Better Geodata

1. Download a proper geodata pack (L2J or L2OFF format) for Interlude
2. Place files in `dist/game/data/geodata/`
3. Run the built-in converter:
   ```bash
   cd dist/game && ./GeoDataConverter.sh
   # Select J (L2J) or O (L2OFF) format
   # Converts to L2D with diagonal movement flags
   ```
4. Restart the server

### Geodata Export

Export loaded geodata at full fidelity from a running server:

```
// In-game as GM:
//geo_export 20 18              // Export one region
//geo_export_all                // Export all 139 regions
//geo_export_all /tmp/geodata/  // Export to custom directory
```

---

## Custom Server Commands

| Command | Description |
|---------|-------------|
| `//geo_export <rx> <ry>` | Export one geodata region to L2D file |
| `//geo_export_all` | Export all loaded regions |
| `//scan_geo <rx> <ry> <blockY>` | Query 256 blocks of geo data (used by scanner) |
| `//scan_geo_check <rx> <ry>` | Check if geodata is loaded for a region |

---

## How the Scanner Works

The traditional approach to geodata scanning (teleporting a character and reading Z coordinates) doesn't work — L2J's `teleToLocation` does `z += 5` without consulting GeoEngine.

Our solution: **custom admin commands that query GeoEngine directly**.

```
Scanner Worker                    L2J Game Server
     │                                  │
     │  SendBypassBuildCmd              │
     │  "scan_geo 20 18 0"             │
     │ ──────────────────────────────►  │
     │                                  │  GeoEngine.getHeightNearest()
     │                                  │  GeoEngine.getNsweNearest()
     │                                  │  × 256 blocks
     │  CreatureSay                     │
     │  "GEODATA|20|18|0|<base64>"     │
     │ ◄──────────────────────────────  │
     │                                  │
     │  (decode base64 → height + NSWE) │
     │  (repeat for blockY 0..255)      │
     │  (write .l2d file)               │
```

Each region = 256 commands. 20 agents = ~2 minutes for all 139 regions.

---

## Contributing

This project is open source and contributions are welcome. Some areas that could use help:

- **Better geodata generation** — movement-based probing to detect actual walkability
- **Pathnode generation** — create pathnode files from geodata for NPC pathfinding
- **Client data extraction** — tools to parse official L2 client files for terrain data
- **Dashboard improvements** — 3D terrain viewer, region comparison tools
- **More admin commands** — NPC spawn visualization, zone boundary rendering
- **Protocol coverage** — implement more packet types in the headless client
- **Testing** — automated tests for the L2 protocol implementation

### How to Contribute

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes
4. Push to your branch
5. Open a Pull Request

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Game Server | Java 21, L2J Mobius C6 Interlude |
| Headless Client | Python 3, raw sockets, Blowfish/RSA crypto |
| Web Dashboards | Flask, Server-Sent Events, vanilla JS |
| Geodata Rendering | NumPy, Pillow |
| Database | MariaDB |
| Build System | Apache Ant |

---

## License

This project is based on [L2J Mobius](https://www.l2jmobius.org/) and is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.html).

The custom tooling (headless client, scanner, geodata editor, management scripts) is also released under GPLv3.

---

## Credits

Created by **elbercasa**

Built with the L2J Mobius C6 Interlude open-source server emulator.

---

*Lineage 2 is a registered trademark of NCSoft Corporation. This project is not affiliated with or endorsed by NCSoft.*
