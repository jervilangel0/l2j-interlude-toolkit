#!/usr/bin/env python3
"""
L2J Geodata Tool - Read, visualize, edit, and export L2D geodata files.

Usage:
  python geodata_tool.py info <file.l2d>
  python geodata_tool.py dump <file.l2d> [--cell X,Y] [--block BX,BY] [--csv output.csv]
  python geodata_tool.py render <file.l2d> [--mode heightmap|nswe|blocks|combined|detail] [--output img.png] [--scale 1]
  python geodata_tool.py edit <file.l2d> --cell X,Y --height H --nswe NSWE [--layer L] [--output edited.l2d]
  python geodata_tool.py unblock <file.l2d> --cell X,Y [--radius R] [--output edited.l2d]
  python geodata_tool.py find-blocked <file.l2d> [--output blocked.csv]
  python geodata_tool.py world2geo <world_x> <world_y>
  python geodata_tool.py geo2world <region_x> <region_y> <cell_x> <cell_y>
"""

import argparse
import csv
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from l2d_parser import (
    GeoRegion, BlockFlat, BlockComplex, BlockMultilayer, Cell,
    parse_l2d, write_l2d, region_to_world_coords, world_to_region_coords,
    REGION_CELLS_X, REGION_CELLS_Y, REGION_BLOCKS_X, REGION_BLOCKS_Y,
    BLOCK_CELLS_X, BLOCK_CELLS_Y, NSWE_ALL, NSWE_ALL_L2D,
    FLAG_N, FLAG_S, FLAG_E, FLAG_W, FLAG_NE, FLAG_NW, FLAG_SE, FLAG_SW,
)


def cmd_info(args):
    """Show region statistics."""
    region = parse_l2d(args.file)
    stats = region.stats

    print(f"Region: {stats['region']}")
    print(f"File: {args.file}")
    print(f"Size: {Path(args.file).stat().st_size:,} bytes")
    print()
    print(f"Blocks: {stats['total_blocks']:,}")
    print(f"  Flat:       {stats['flat_blocks']:,} ({stats['flat_blocks']/stats['total_blocks']*100:.1f}%)")
    print(f"  Complex:    {stats['complex_blocks']:,} ({stats['complex_blocks']/stats['total_blocks']*100:.1f}%)")
    print(f"  Multilayer: {stats['multilayer_blocks']:,} ({stats['multilayer_blocks']/stats['total_blocks']*100:.1f}%)")
    print()

    # Height stats
    h_min, h_max = 32767, -32768
    blocked_count = 0
    partial_count = 0
    total_cells = 0
    max_layers = 0

    for bx in range(REGION_BLOCKS_X):
        for by in range(REGION_BLOCKS_Y):
            block = region.get_block(bx, by)
            for lx in range(BLOCK_CELLS_X):
                for ly in range(BLOCK_CELLS_Y):
                    layers = block.get_layers(lx, ly)
                    max_layers = max(max_layers, len(layers))
                    for cell in layers:
                        total_cells += 1
                        h_min = min(h_min, cell.height)
                        h_max = max(h_max, cell.height)
                        cardinal = cell.nswe & NSWE_ALL
                        if cardinal == 0:
                            blocked_count += 1
                        elif cardinal != NSWE_ALL:
                            partial_count += 1

    print(f"Cells: {total_cells:,}")
    print(f"  Height range: {h_min} to {h_max}")
    print(f"  Fully blocked: {blocked_count:,}")
    print(f"  Partially blocked: {partial_count:,}")
    print(f"  Max layers: {max_layers}")


def cmd_dump(args):
    """Dump cell data."""
    region = parse_l2d(args.file)

    if args.cell:
        cx, cy = map(int, args.cell.split(","))
        layers = region.get_layers(cx, cy)
        wx, wy = region_to_world_coords(region.region_x, region.region_y, cx, cy)
        print(f"Cell ({cx}, {cy}) | World ({wx}, {wy})")
        print(f"Layers: {len(layers)}")
        for i, cell in enumerate(layers):
            print(f"  Layer {i}: height={cell.height}, nswe=0x{cell.nswe:02X} ({cell.nswe_str()})")
        return

    if args.block:
        bx, by = map(int, args.block.split(","))
        block = region.get_block(bx, by)
        print(f"Block ({bx}, {by}) - Type: {type(block).__name__}")
        for lx in range(BLOCK_CELLS_X):
            for ly in range(BLOCK_CELLS_Y):
                cell = block.get_cell(lx, ly)
                cx = bx * BLOCK_CELLS_X + lx
                cy = by * BLOCK_CELLS_Y + ly
                print(f"  Cell ({cx},{cy}): h={cell.height:>6}, nswe={cell.nswe_str()}")
        return

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["cell_x", "cell_y", "world_x", "world_y", "height", "nswe_hex", "nswe_dirs", "layers"])
            for cx in range(REGION_CELLS_X):
                for cy in range(REGION_CELLS_Y):
                    layers = region.get_layers(cx, cy)
                    cell = layers[0]
                    wx, wy = region_to_world_coords(region.region_x, region.region_y, cx, cy)
                    writer.writerow([cx, cy, wx, wy, cell.height, f"0x{cell.nswe:02X}", cell.nswe_str(), len(layers)])
        print(f"Exported {REGION_CELLS_X * REGION_CELLS_Y:,} cells to {args.csv}")
        return

    print("Specify --cell X,Y or --block BX,BY or --csv output.csv")


def cmd_render(args):
    """Render geodata as image."""
    from renderer import (
        render_heightmap, render_nswe, render_block_types,
        render_combined, render_cell_detail,
    )

    region = parse_l2d(args.file)
    mode = args.mode or "combined"
    scale = args.scale or 1
    output = args.output or f"{Path(args.file).stem}_{mode}.png"

    if mode == "heightmap":
        img = render_heightmap(region, scale=scale)
    elif mode == "nswe":
        img = render_nswe(region, scale=scale)
    elif mode == "blocks":
        img = render_block_types(region, scale=scale)
    elif mode == "combined":
        img = render_combined(region, scale=scale)
    elif mode == "detail":
        if not args.cell:
            print("--cell X,Y required for detail mode")
            return
        cx, cy = map(int, args.cell.split(","))
        radius = args.radius or 16
        img = render_cell_detail(region, cx, cy, radius=radius, cell_size=20)
    else:
        print(f"Unknown mode: {mode}")
        return

    img.save(output)
    print(f"Saved {mode} render to {output} ({img.size[0]}x{img.size[1]})")


def cmd_edit(args):
    """Edit a specific cell."""
    region = parse_l2d(args.file)
    cx, cy = map(int, args.cell.split(","))
    layer = args.layer or 0

    cell = region.get_cell(cx, cy, layer)
    print(f"Before: height={cell.height}, nswe=0x{cell.nswe:02X} ({cell.nswe_str()})")

    bx = cx // BLOCK_CELLS_X
    by = cy // BLOCK_CELLS_Y
    lx = cx % BLOCK_CELLS_X
    ly = cy % BLOCK_CELLS_Y
    block = region.get_block(bx, by)

    new_height = int(args.height) if args.height is not None else cell.height
    new_nswe = _parse_nswe(args.nswe) if args.nswe is not None else cell.nswe

    if isinstance(block, BlockFlat):
        print("Warning: Flat block - editing will only change the shared height for all 64 cells.")
        block.height = new_height
    elif isinstance(block, BlockComplex):
        block.set_cell(lx, ly, new_height, new_nswe)
    elif isinstance(block, BlockMultilayer):
        block.set_cell(lx, ly, layer, new_height, new_nswe)

    cell = region.get_cell(cx, cy, layer)
    print(f"After:  height={cell.height}, nswe=0x{cell.nswe:02X} ({cell.nswe_str()})")

    output = args.output or args.file
    write_l2d(region, output)
    print(f"Saved to {output}")


def cmd_unblock(args):
    """Unblock cells in a radius (make them fully walkable)."""
    region = parse_l2d(args.file)
    cx, cy = map(int, args.cell.split(","))
    radius = args.radius or 0
    count = 0

    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            x = cx + dx
            y = cy + dy
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
                for layer_idx, cell in enumerate(block.get_layers(lx, ly)):
                    if (cell.nswe & NSWE_ALL) != NSWE_ALL:
                        block.set_cell(lx, ly, layer_idx, cell.height, NSWE_ALL_L2D)
                        count += 1

    output = args.output or args.file
    write_l2d(region, output)
    print(f"Unblocked {count} cells in radius {radius} around ({cx},{cy}). Saved to {output}")


def cmd_find_blocked(args):
    """Find all blocked or partially blocked cells."""
    region = parse_l2d(args.file)
    results = []

    for cx in range(REGION_CELLS_X):
        for cy in range(REGION_CELLS_Y):
            cell = region.get_cell(cx, cy)
            cardinal = cell.nswe & NSWE_ALL
            if cardinal != NSWE_ALL:
                wx, wy = region_to_world_coords(region.region_x, region.region_y, cx, cy)
                status = "BLOCKED" if cardinal == 0 else "PARTIAL"
                results.append((cx, cy, wx, wy, cell.height, cell.nswe, cell.nswe_str(), status))

    if args.output:
        with open(args.output, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["cell_x", "cell_y", "world_x", "world_y", "height", "nswe_hex", "nswe_dirs", "status"])
            for row in results:
                writer.writerow([row[0], row[1], row[2], row[3], row[4], f"0x{row[5]:02X}", row[6], row[7]])
        print(f"Found {len(results):,} blocked/partial cells. Exported to {args.output}")
    else:
        blocked = sum(1 for r in results if r[7] == "BLOCKED")
        partial = sum(1 for r in results if r[7] == "PARTIAL")
        print(f"Found {len(results):,} non-walkable cells:")
        print(f"  Fully blocked: {blocked:,}")
        print(f"  Partially blocked: {partial:,}")
        if results:
            print(f"\nFirst 20:")
            for r in results[:20]:
                print(f"  ({r[0]:>4},{r[1]:>4}) world({r[2]:>7},{r[3]:>7}) h={r[4]:>6} {r[7]:<8} {r[6]}")


def cmd_world2geo(args):
    """Convert world coordinates to region+cell."""
    rx, ry, cx, cy = world_to_region_coords(int(args.world_x), int(args.world_y))
    print(f"World ({args.world_x}, {args.world_y}) -> Region {rx}_{ry}, Cell ({cx}, {cy})")
    print(f"File: {rx}_{ry}.l2d")


def cmd_geo2world(args):
    """Convert region+cell to world coordinates."""
    wx, wy = region_to_world_coords(int(args.region_x), int(args.region_y), int(args.cell_x), int(args.cell_y))
    print(f"Region {args.region_x}_{args.region_y} Cell ({args.cell_x}, {args.cell_y}) -> World ({wx}, {wy})")


def _parse_nswe(value: str) -> int:
    """Parse NSWE from hex string or direction letters."""
    if value.startswith("0x") or value.startswith("0X"):
        return int(value, 16)

    if value.upper() == "ALL":
        return NSWE_ALL_L2D

    if value.upper() == "NONE" or value == "0":
        return 0

    result = 0
    v = value.upper()
    # Check multi-char directions first
    if "NE" in v: result |= FLAG_NE; v = v.replace("NE", "", 1)
    if "NW" in v: result |= FLAG_NW; v = v.replace("NW", "", 1)
    if "SE" in v: result |= FLAG_SE; v = v.replace("SE", "", 1)
    if "SW" in v: result |= FLAG_SW; v = v.replace("SW", "", 1)
    if "N" in v: result |= FLAG_N
    if "S" in v: result |= FLAG_S
    if "E" in v: result |= FLAG_E
    if "W" in v: result |= FLAG_W
    return result


def main():
    parser = argparse.ArgumentParser(description="L2J Geodata Tool - Read, visualize, edit L2D files")
    sub = parser.add_subparsers(dest="command")

    # info
    p = sub.add_parser("info", help="Show region statistics")
    p.add_argument("file", help="L2D geodata file")

    # dump
    p = sub.add_parser("dump", help="Dump cell data")
    p.add_argument("file", help="L2D geodata file")
    p.add_argument("--cell", help="Cell coordinates X,Y")
    p.add_argument("--block", help="Block coordinates BX,BY")
    p.add_argument("--csv", help="Export all cells to CSV")

    # render
    p = sub.add_parser("render", help="Render geodata as image")
    p.add_argument("file", help="L2D geodata file")
    p.add_argument("--mode", choices=["heightmap", "nswe", "blocks", "combined", "detail"], default="combined")
    p.add_argument("--output", "-o", help="Output image path")
    p.add_argument("--scale", type=int, default=1, help="Scale factor")
    p.add_argument("--cell", help="Center cell X,Y (for detail mode)")
    p.add_argument("--radius", type=int, default=16, help="Radius in cells (for detail mode)")

    # edit
    p = sub.add_parser("edit", help="Edit a specific cell")
    p.add_argument("file", help="L2D geodata file")
    p.add_argument("--cell", required=True, help="Cell coordinates X,Y")
    p.add_argument("--height", help="New height value")
    p.add_argument("--nswe", help="New NSWE flags (hex: 0xFF, dirs: NSEW, ALL, NONE)")
    p.add_argument("--layer", type=int, default=0, help="Layer index for multilayer blocks")
    p.add_argument("--output", "-o", help="Output file (default: overwrite)")

    # unblock
    p = sub.add_parser("unblock", help="Make cells walkable in a radius")
    p.add_argument("file", help="L2D geodata file")
    p.add_argument("--cell", required=True, help="Center cell X,Y")
    p.add_argument("--radius", type=int, default=0, help="Radius in cells")
    p.add_argument("--output", "-o", help="Output file (default: overwrite)")

    # find-blocked
    p = sub.add_parser("find-blocked", help="Find blocked/partial cells")
    p.add_argument("file", help="L2D geodata file")
    p.add_argument("--output", "-o", help="Export to CSV")

    # world2geo
    p = sub.add_parser("world2geo", help="Convert world coords to region+cell")
    p.add_argument("world_x", help="World X coordinate")
    p.add_argument("world_y", help="World Y coordinate")

    # geo2world
    p = sub.add_parser("geo2world", help="Convert region+cell to world coords")
    p.add_argument("region_x", help="Region X")
    p.add_argument("region_y", help="Region Y")
    p.add_argument("cell_x", help="Cell X")
    p.add_argument("cell_y", help="Cell Y")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "info": cmd_info,
        "dump": cmd_dump,
        "render": cmd_render,
        "edit": cmd_edit,
        "unblock": cmd_unblock,
        "find-blocked": cmd_find_blocked,
        "world2geo": cmd_world2geo,
        "geo2world": cmd_geo2world,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
