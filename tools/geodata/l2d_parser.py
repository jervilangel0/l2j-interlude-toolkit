from __future__ import annotations

"""
L2D Geodata Parser for L2J Mobius C6 Interlude

Binary format:
  Region file = 256x256 blocks, each block = 8x8 cells
  Block types:
    0xD0 (Flat)       - 2 bytes: height. All 64 cells same height, fully walkable.
    0xD1 (Complex)    - 64 cells x 3 bytes: [nswe, height_lo, height_hi]
    0xD2 (Multilayer) - Variable. Per cell: [layer_count, (nswe, height_lo, height_hi) * layers]

  NSWE byte (L2D):
    bit 0 = East,  bit 1 = West,  bit 2 = South, bit 3 = North
    bit 4 = SE,    bit 5 = SW,    bit 6 = NE,    bit 7 = NW
"""

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

# Constants matching GeoStructure.java
BLOCK_CELLS_X = 8
BLOCK_CELLS_Y = 8
BLOCK_CELLS = BLOCK_CELLS_X * BLOCK_CELLS_Y  # 64
REGION_BLOCKS_X = 256
REGION_BLOCKS_Y = 256
REGION_BLOCKS = REGION_BLOCKS_X * REGION_BLOCKS_Y  # 65536
REGION_CELLS_X = REGION_BLOCKS_X * BLOCK_CELLS_X  # 2048
REGION_CELLS_Y = REGION_BLOCKS_Y * BLOCK_CELLS_Y  # 2048

TYPE_FLAT = 0xD0
TYPE_COMPLEX = 0xD1
TYPE_MULTILAYER = 0xD2

FLAG_E  = 1 << 0
FLAG_W  = 1 << 1
FLAG_S  = 1 << 2
FLAG_N  = 1 << 3
FLAG_SE = 1 << 4
FLAG_SW = 1 << 5
FLAG_NE = 1 << 6
FLAG_NW = 1 << 7

NSWE_ALL = 0x0F      # all cardinal directions
NSWE_ALL_L2D = 0xFF  # all cardinal + diagonal


@dataclass
class Cell:
    height: int
    nswe: int

    @property
    def can_move_north(self) -> bool:
        return bool(self.nswe & FLAG_N)

    @property
    def can_move_south(self) -> bool:
        return bool(self.nswe & FLAG_S)

    @property
    def can_move_east(self) -> bool:
        return bool(self.nswe & FLAG_E)

    @property
    def can_move_west(self) -> bool:
        return bool(self.nswe & FLAG_W)

    @property
    def is_fully_walkable(self) -> bool:
        return (self.nswe & NSWE_ALL) == NSWE_ALL

    @property
    def is_blocked(self) -> bool:
        return (self.nswe & NSWE_ALL) == 0

    def nswe_str(self) -> str:
        dirs = []
        if self.nswe & FLAG_N: dirs.append("N")
        if self.nswe & FLAG_S: dirs.append("S")
        if self.nswe & FLAG_E: dirs.append("E")
        if self.nswe & FLAG_W: dirs.append("W")
        if self.nswe & FLAG_NE: dirs.append("NE")
        if self.nswe & FLAG_NW: dirs.append("NW")
        if self.nswe & FLAG_SE: dirs.append("SE")
        if self.nswe & FLAG_SW: dirs.append("SW")
        return ",".join(dirs) if dirs else "BLOCKED"


@dataclass
class BlockFlat:
    block_type: int = TYPE_FLAT
    height: int = 0

    def get_cell(self, x: int, y: int, layer: int = 0) -> Cell:
        return Cell(height=self.height, nswe=NSWE_ALL_L2D)

    def get_layers(self, x: int, y: int) -> list[Cell]:
        return [self.get_cell(x, y)]

    @property
    def cell_count(self) -> int:
        return BLOCK_CELLS

    @property
    def layer_count(self) -> int:
        return 1


@dataclass
class BlockComplex:
    block_type: int = TYPE_COMPLEX
    cells: list[Cell] = field(default_factory=list)  # 64 cells

    def get_cell(self, x: int, y: int, layer: int = 0) -> Cell:
        return self.cells[x * BLOCK_CELLS_Y + y]

    def get_layers(self, x: int, y: int) -> list[Cell]:
        return [self.get_cell(x, y)]

    def set_cell(self, x: int, y: int, height: int, nswe: int):
        self.cells[x * BLOCK_CELLS_Y + y] = Cell(height=height, nswe=nswe)

    @property
    def cell_count(self) -> int:
        return len(self.cells)

    @property
    def layer_count(self) -> int:
        return 1


@dataclass
class BlockMultilayer:
    block_type: int = TYPE_MULTILAYER
    cell_layers: list[list[Cell]] = field(default_factory=list)  # 64 cells, each with N layers

    def get_cell(self, x: int, y: int, layer: int = 0) -> Cell:
        layers = self.cell_layers[x * BLOCK_CELLS_Y + y]
        if layer < len(layers):
            return layers[layer]
        return layers[0]

    def get_layers(self, x: int, y: int) -> list[Cell]:
        return self.cell_layers[x * BLOCK_CELLS_Y + y]

    def set_cell(self, x: int, y: int, layer: int, height: int, nswe: int):
        self.cell_layers[x * BLOCK_CELLS_Y + y][layer] = Cell(height=height, nswe=nswe)

    @property
    def cell_count(self) -> int:
        return len(self.cell_layers)

    @property
    def layer_count(self) -> int:
        return max(len(layers) for layers in self.cell_layers) if self.cell_layers else 0


Block = Union[BlockFlat, BlockComplex, BlockMultilayer]


@dataclass
class GeoRegion:
    region_x: int
    region_y: int
    blocks: list[Block]  # 65536 blocks (256x256)

    def get_block(self, bx: int, by: int) -> Block:
        return self.blocks[bx * REGION_BLOCKS_Y + by]

    def get_cell(self, cx: int, cy: int, layer: int = 0) -> Cell:
        bx = cx // BLOCK_CELLS_X
        by = cy // BLOCK_CELLS_Y
        lx = cx % BLOCK_CELLS_X
        ly = cy % BLOCK_CELLS_Y
        return self.get_block(bx, by).get_cell(lx, ly, layer)

    def get_layers(self, cx: int, cy: int) -> list[Cell]:
        bx = cx // BLOCK_CELLS_X
        by = cy // BLOCK_CELLS_Y
        lx = cx % BLOCK_CELLS_X
        ly = cy % BLOCK_CELLS_Y
        return self.get_block(bx, by).get_layers(lx, ly)

    def get_height(self, cx: int, cy: int) -> int:
        return self.get_cell(cx, cy).height

    def get_nswe(self, cx: int, cy: int) -> int:
        return self.get_cell(cx, cy).nswe

    @property
    def stats(self) -> dict:
        flat = sum(1 for b in self.blocks if isinstance(b, BlockFlat))
        complex_ = sum(1 for b in self.blocks if isinstance(b, BlockComplex))
        multi = sum(1 for b in self.blocks if isinstance(b, BlockMultilayer))
        return {
            "region": f"{self.region_x}_{self.region_y}",
            "flat_blocks": flat,
            "complex_blocks": complex_,
            "multilayer_blocks": multi,
            "total_blocks": len(self.blocks),
        }


def parse_l2d(filepath: str | Path) -> GeoRegion:
    """Parse an L2D geodata file and return a GeoRegion."""
    filepath = Path(filepath)
    name = filepath.stem  # e.g. "22_16"
    parts = name.split("_")
    try:
        region_x, region_y = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        region_x, region_y = 0, 0

    data = filepath.read_bytes()
    pos = 0
    blocks: list[Block] = []

    for _ in range(REGION_BLOCKS):
        block_type = data[pos]
        pos += 1

        if block_type == TYPE_FLAT:
            height = struct.unpack_from("<h", data, pos)[0]
            pos += 2
            blocks.append(BlockFlat(height=height))

        elif block_type == TYPE_COMPLEX:
            cells = []
            for _ in range(BLOCK_CELLS):
                nswe = data[pos]
                height = struct.unpack_from("<h", data, pos + 1)[0]
                pos += 3
                cells.append(Cell(height=height, nswe=nswe))
            blocks.append(BlockComplex(cells=cells))

        elif block_type == TYPE_MULTILAYER:
            cell_layers = []
            for _ in range(BLOCK_CELLS):
                layer_count = data[pos]
                pos += 1
                layers = []
                for _ in range(layer_count):
                    nswe = data[pos]
                    height = struct.unpack_from("<h", data, pos + 1)[0]
                    pos += 3
                    layers.append(Cell(height=height, nswe=nswe))
                cell_layers.append(layers)
            blocks.append(BlockMultilayer(cell_layers=cell_layers))

        else:
            raise ValueError(f"Unknown block type 0x{block_type:02X} at offset {pos - 1}")

    return GeoRegion(region_x=region_x, region_y=region_y, blocks=blocks)


def write_l2d(region: GeoRegion, filepath: str | Path):
    """Write a GeoRegion back to L2D binary format."""
    filepath = Path(filepath)
    out = bytearray()

    for block in region.blocks:
        if isinstance(block, BlockFlat):
            out.append(TYPE_FLAT)
            out.extend(struct.pack("<h", block.height))

        elif isinstance(block, BlockComplex):
            out.append(TYPE_COMPLEX)
            for cell in block.cells:
                out.append(cell.nswe & 0xFF)
                out.extend(struct.pack("<h", cell.height))

        elif isinstance(block, BlockMultilayer):
            out.append(TYPE_MULTILAYER)
            for layers in block.cell_layers:
                out.append(len(layers))
                for cell in layers:
                    out.append(cell.nswe & 0xFF)
                    out.extend(struct.pack("<h", cell.height))

    filepath.write_bytes(bytes(out))


def region_to_world_coords(region_x: int, region_y: int, cell_x: int, cell_y: int) -> tuple[int, int]:
    """Convert region + cell coordinates to L2 world coordinates.
    World origin offset: tile 11,10 maps to world coordinate 0,0 area.
    Each cell = 16 world units.
    """
    world_x = ((region_x - 11) * REGION_CELLS_X + cell_x) * 16 + -327680
    world_y = ((region_y - 10) * REGION_CELLS_Y + cell_y) * 16 + -262144
    return world_x, world_y


def world_to_region_coords(world_x: int, world_y: int) -> tuple[int, int, int, int]:
    """Convert world coordinates to region + cell coordinates.
    Returns: (region_x, region_y, cell_x, cell_y)
    """
    geo_x = (world_x + 327680) // 16
    geo_y = (world_y + 262144) // 16
    region_x = geo_x // REGION_CELLS_X + 11
    region_y = geo_y // REGION_CELLS_Y + 10
    cell_x = geo_x % REGION_CELLS_X
    cell_y = geo_y % REGION_CELLS_Y
    return region_x, region_y, cell_x, cell_y
