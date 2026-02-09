from __future__ import annotations

"""
L2D Geodata Visual Renderer

Renders geodata regions as images:
  - Height map (grayscale)
  - NSWE movement flags (color-coded)
  - Block type map (flat/complex/multilayer)
  - Combined overlay
"""

import numpy as np
from pathlib import Path
from l2d_parser import (
    GeoRegion, BlockFlat, BlockComplex, BlockMultilayer,
    REGION_CELLS_X, REGION_CELLS_Y, REGION_BLOCKS_X, REGION_BLOCKS_Y,
    BLOCK_CELLS_X, BLOCK_CELLS_Y,
    FLAG_N, FLAG_S, FLAG_E, FLAG_W, NSWE_ALL,
    parse_l2d,
)

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def _check_pil():
    if not HAS_PIL:
        raise ImportError("Pillow is required for rendering. Install with: pip install Pillow")


def extract_height_grid(region: GeoRegion) -> np.ndarray:
    """Extract a 2048x2048 height grid from a region (top layer only)."""
    grid = np.zeros((REGION_CELLS_X, REGION_CELLS_Y), dtype=np.int16)

    for bx in range(REGION_BLOCKS_X):
        for by in range(REGION_BLOCKS_Y):
            block = region.get_block(bx, by)
            for lx in range(BLOCK_CELLS_X):
                for ly in range(BLOCK_CELLS_Y):
                    cx = bx * BLOCK_CELLS_X + lx
                    cy = by * BLOCK_CELLS_Y + ly
                    cell = block.get_cell(lx, ly)
                    grid[cx, cy] = cell.height

    return grid


def extract_nswe_grid(region: GeoRegion) -> np.ndarray:
    """Extract a 2048x2048 NSWE flags grid."""
    grid = np.zeros((REGION_CELLS_X, REGION_CELLS_Y), dtype=np.uint8)

    for bx in range(REGION_BLOCKS_X):
        for by in range(REGION_BLOCKS_Y):
            block = region.get_block(bx, by)
            for lx in range(BLOCK_CELLS_X):
                for ly in range(BLOCK_CELLS_Y):
                    cx = bx * BLOCK_CELLS_X + lx
                    cy = by * BLOCK_CELLS_Y + ly
                    cell = block.get_cell(lx, ly)
                    grid[cx, cy] = cell.nswe

    return grid


def extract_layer_count_grid(region: GeoRegion) -> np.ndarray:
    """Extract layer count per cell."""
    grid = np.zeros((REGION_CELLS_X, REGION_CELLS_Y), dtype=np.uint8)

    for bx in range(REGION_BLOCKS_X):
        for by in range(REGION_BLOCKS_Y):
            block = region.get_block(bx, by)
            for lx in range(BLOCK_CELLS_X):
                for ly in range(BLOCK_CELLS_Y):
                    cx = bx * BLOCK_CELLS_X + lx
                    cy = by * BLOCK_CELLS_Y + ly
                    layers = block.get_layers(lx, ly)
                    grid[cx, cy] = len(layers)

    return grid


def render_heightmap(region: GeoRegion, scale: int = 1) -> "Image.Image":
    """Render height map as grayscale image. Brighter = higher."""
    _check_pil()
    grid = extract_height_grid(region)

    h_min = grid.min()
    h_max = grid.max()
    h_range = max(h_max - h_min, 1)

    normalized = ((grid.astype(np.float32) - h_min) / h_range * 255).astype(np.uint8)
    img = Image.fromarray(normalized.T, mode="L")

    if scale > 1:
        img = img.resize((REGION_CELLS_X * scale, REGION_CELLS_Y * scale), Image.NEAREST)

    return img


def render_nswe(region: GeoRegion, scale: int = 1) -> "Image.Image":
    """Render NSWE movement flags as color-coded image.

    Colors:
      Green  = fully walkable (all cardinal directions)
      Red    = fully blocked (no movement)
      Yellow = partially blocked (some directions)
      Blue   = has multilayer data
    """
    _check_pil()
    nswe_grid = extract_nswe_grid(region)
    layer_grid = extract_layer_count_grid(region)

    rgb = np.zeros((REGION_CELLS_X, REGION_CELLS_Y, 3), dtype=np.uint8)

    # Fully walkable = green
    walkable = (nswe_grid & NSWE_ALL) == NSWE_ALL
    rgb[walkable] = [40, 180, 40]

    # Partially blocked = yellow
    partial = (~walkable) & ((nswe_grid & NSWE_ALL) != 0)
    rgb[partial] = [220, 200, 40]

    # Fully blocked = red
    blocked = (nswe_grid & NSWE_ALL) == 0
    rgb[blocked] = [200, 40, 40]

    # Multilayer overlay = blue tint
    multi = layer_grid > 1
    rgb[multi, 2] = np.minimum(rgb[multi, 2].astype(np.int16) + 120, 255).astype(np.uint8)

    img = Image.fromarray(rgb.transpose(1, 0, 2), mode="RGB")

    if scale > 1:
        img = img.resize((REGION_CELLS_X * scale, REGION_CELLS_Y * scale), Image.NEAREST)

    return img


def render_block_types(region: GeoRegion, scale: int = 1) -> "Image.Image":
    """Render block type map.

    Colors:
      Dark gray   = Flat (terrain with no detail)
      Light gray  = Complex (detailed single-layer)
      Cyan        = Multilayer (bridges, tunnels, etc.)
    """
    _check_pil()
    rgb = np.zeros((REGION_CELLS_X, REGION_CELLS_Y, 3), dtype=np.uint8)

    for bx in range(REGION_BLOCKS_X):
        for by in range(REGION_BLOCKS_Y):
            block = region.get_block(bx, by)
            cx_start = bx * BLOCK_CELLS_X
            cy_start = by * BLOCK_CELLS_Y
            cx_end = cx_start + BLOCK_CELLS_X
            cy_end = cy_start + BLOCK_CELLS_Y

            if isinstance(block, BlockFlat):
                rgb[cx_start:cx_end, cy_start:cy_end] = [60, 60, 60]
            elif isinstance(block, BlockComplex):
                rgb[cx_start:cx_end, cy_start:cy_end] = [160, 160, 160]
            elif isinstance(block, BlockMultilayer):
                rgb[cx_start:cx_end, cy_start:cy_end] = [40, 200, 200]

    img = Image.fromarray(rgb.transpose(1, 0, 2), mode="RGB")

    if scale > 1:
        img = img.resize((REGION_CELLS_X * scale, REGION_CELLS_Y * scale), Image.NEAREST)

    return img


def render_combined(region: GeoRegion, scale: int = 1) -> "Image.Image":
    """Render height map with NSWE overlay.

    Height controls brightness, NSWE controls color tint:
      Walkable areas = green-ish
      Blocked areas  = red-ish
      Partial blocks = yellow-ish
    """
    _check_pil()
    height_grid = extract_height_grid(region)
    nswe_grid = extract_nswe_grid(region)

    h_min = height_grid.min()
    h_max = height_grid.max()
    h_range = max(h_max - h_min, 1)
    brightness = ((height_grid.astype(np.float32) - h_min) / h_range * 200 + 30).astype(np.uint8)

    rgb = np.zeros((REGION_CELLS_X, REGION_CELLS_Y, 3), dtype=np.uint8)

    walkable = (nswe_grid & NSWE_ALL) == NSWE_ALL
    partial = (~walkable) & ((nswe_grid & NSWE_ALL) != 0)
    blocked = (nswe_grid & NSWE_ALL) == 0

    # Green channel for walkable
    rgb[walkable, 0] = (brightness[walkable] * 0.3).astype(np.uint8)
    rgb[walkable, 1] = brightness[walkable]
    rgb[walkable, 2] = (brightness[walkable] * 0.3).astype(np.uint8)

    # Yellow for partial
    rgb[partial, 0] = brightness[partial]
    rgb[partial, 1] = (brightness[partial] * 0.85).astype(np.uint8)
    rgb[partial, 2] = (brightness[partial] * 0.15).astype(np.uint8)

    # Red for blocked
    rgb[blocked, 0] = brightness[blocked]
    rgb[blocked, 1] = (brightness[blocked] * 0.2).astype(np.uint8)
    rgb[blocked, 2] = (brightness[blocked] * 0.2).astype(np.uint8)

    img = Image.fromarray(rgb.transpose(1, 0, 2), mode="RGB")

    if scale > 1:
        img = img.resize((REGION_CELLS_X * scale, REGION_CELLS_Y * scale), Image.NEAREST)

    return img


def render_cell_detail(region: GeoRegion, cx: int, cy: int, radius: int = 16, cell_size: int = 20) -> "Image.Image":
    """Render a zoomed-in view of cells around a specific coordinate.

    Shows individual cell movement arrows and height values.
    """
    _check_pil()
    size = (radius * 2 + 1) * cell_size
    img = Image.new("RGB", (size, size), (30, 30, 30))
    draw = ImageDraw.Draw(img)

    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            x = cx + dx
            y = cy + dy
            if x < 0 or y < 0 or x >= REGION_CELLS_X or y >= REGION_CELLS_Y:
                continue

            cell = region.get_cell(x, y)
            px = (dx + radius) * cell_size
            py = (dy + radius) * cell_size

            # Background color based on walkability
            nswe = cell.nswe & NSWE_ALL
            if nswe == NSWE_ALL:
                bg = (40, 120, 40)
            elif nswe == 0:
                bg = (140, 30, 30)
            else:
                bg = (160, 140, 30)

            draw.rectangle([px, py, px + cell_size - 1, py + cell_size - 1], fill=bg, outline=(60, 60, 60))

            # Draw direction arrows
            mid_x = px + cell_size // 2
            mid_y = py + cell_size // 2
            arrow_len = cell_size // 3
            arrow_color = (220, 220, 220)

            if cell.nswe & FLAG_N:
                draw.line([mid_x, mid_y, mid_x, mid_y - arrow_len], fill=arrow_color)
            if cell.nswe & FLAG_S:
                draw.line([mid_x, mid_y, mid_x, mid_y + arrow_len], fill=arrow_color)
            if cell.nswe & FLAG_E:
                draw.line([mid_x, mid_y, mid_x + arrow_len, mid_y], fill=arrow_color)
            if cell.nswe & FLAG_W:
                draw.line([mid_x, mid_y, mid_x - arrow_len, mid_y], fill=arrow_color)

    # Highlight center cell
    center_px = radius * cell_size
    center_py = radius * cell_size
    draw.rectangle(
        [center_px, center_py, center_px + cell_size - 1, center_py + cell_size - 1],
        outline=(255, 255, 0), width=2
    )

    return img
