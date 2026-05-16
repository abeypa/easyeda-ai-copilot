"""
ELK-inspired layout engine for circuit assembly.

Primary approach: Pure Python hierarchical layout algorithm that:
  1. Groups components by block
  2. Positions blocks in a grid with proper spacing
  3. Places components within each block
  4. Generates routed wire edges via a simple grid-based router
  5. Computes block bounding rectangles

This produces clean, non-overlapping layouts without needing Node.js/elkjs.
The output format matches CircuitAssembly exactly (edges with sections/bendPoints).

Component sizing (in schematic grid units, ~100 units = 1 grid cell in EasyEDA Pro):
  - Passive (R,C,L,F): 60 wide x 30 tall
  - Transistor (Q): 60 wide x 60 tall
  - Diode (D): 60 wide x 40 tall
  - IC/MCU (U): 100 wide x based on pin count
  - Connector (J): 50 wide x 20 x pin_count tall
  - Crystal (X): 60 wide x 40 tall
  - Default: 80 wide x 60 tall

Spacing:
  - Between components: 40 units
  - Between blocks: 120 units
  - Block padding: 60 units
"""

from __future__ import annotations
import logging
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from models.circuit import (
    BaseComponent,
    Block,
    CircuitAssembly,
    CircuitMetadata,
    CircuitStruct,
    ComponentPos,
    ComponentWithPos,
    ElkEdge,
    ElkEdgeSection,
    ElkPoint,
    BlockRect,
    AddedNet,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Sizing constants (EasyEDA schematic coordinate units)
# --------------------------------------------------------------------------
COMP_SPACING = 40        # Gap between components within a block
BLOCK_PADDING = 60       # Padding inside block boundary
BLOCK_SPACING = 120      # Gap between blocks

# Component size lookup by designator prefix
COMP_SIZES: Dict[str, Tuple[int, int]] = {
    "R": (60, 30),
    "C": (60, 30),
    "L": (60, 30),
    "F": (60, 30),
    "Q": (60, 60),
    "D": (60, 40),
    "X": (60, 40),
    "Y": (60, 40),
    "J": (50, 40),
    "P": (50, 40),
    "SW": (60, 40),
    "K": (80, 60),
    "U": (100, 60),
    "IC": (100, 60),
}
DEFAULT_COMP_SIZE = (80, 60)

# How many pins on an IC add extra height (per 2 pins)
IC_HEIGHT_PER_2_PINS = 20


def _get_component_size(comp: BaseComponent) -> Tuple[int, int]:
    """Return (width, height) for a component based on its designator."""
    prefix = ""
    for c in comp.designator:
        if c.isalpha():
            prefix += c.upper()
        else:
            break

    if prefix in COMP_SIZES:
        w, h = COMP_SIZES[prefix]
        # For ICs, scale height by pin count
        if prefix in ("U", "IC") and len(comp.pins) > 4:
            extra = ((len(comp.pins) - 4) // 2) * IC_HEIGHT_PER_2_PINS
            h = max(h, 60 + extra)
        # For connectors, scale height by pin count
        if prefix in ("J", "P") and len(comp.pins) > 2:
            h = max(h, 20 * len(comp.pins))
        return w, h

    return DEFAULT_COMP_SIZE


# --------------------------------------------------------------------------
# Block graph helpers
# --------------------------------------------------------------------------

def _build_block_graph(blocks: List[Block]) -> Dict[str, List[str]]:
    """Return adjacency: block_name -> list of successor block names."""
    graph: Dict[str, List[str]] = {}
    for b in blocks:
        graph[b.name] = b.next_block_names or []
    return graph


def _topological_order(blocks: List[Block]) -> List[str]:
    """
    Return block names in topological order (sources first).
    Falls back to declaration order if there are cycles.
    """
    graph = _build_block_graph(blocks)
    visited: Set[str] = set()
    order: List[str] = []

    def dfs(name: str, stack: Set[str]):
        if name in stack:
            return  # cycle detected - skip
        if name in visited:
            return
        stack.add(name)
        for nxt in graph.get(name, []):
            dfs(nxt, stack)
        stack.discard(name)
        visited.add(name)
        order.append(name)

    for b in blocks:
        if b.name not in visited:
            dfs(b.name, set())

    # order is in reverse post-order -> reverse it for topological order
    order.reverse()
    return order


# --------------------------------------------------------------------------
# Layout algorithm
# --------------------------------------------------------------------------

class CircuitLayout:
    """
    Hierarchical circuit layout:
    1. Arrange blocks in a left-to-right topology flow
    2. Place components within each block
    3. Route wire edges between matching signal_names
    """

    def __init__(self, circuit: CircuitStruct):
        self.circuit = circuit
        self.components = circuit.components
        self.blocks = circuit.blocks

        # Group components by block_name
        self.block_components: Dict[str, List[BaseComponent]] = defaultdict(list)
        for comp in self.components:
            self.block_components[comp.block_name].append(comp)

        # Components that don't belong to any block
        block_names = {b.name for b in self.blocks}
        for comp in self.components:
            if comp.block_name not in block_names:
                self.block_components["__ungrouped__"].append(comp)

    def compute_block_layout(self) -> Dict[str, Tuple[int, int, int, int]]:
        """
        Compute (x, y, width, height) for each block in schematic coordinates.
        Blocks are arranged in a SINGLE HORIZONTAL ROW following topology order.
        This ensures clean left-to-right signal flow.
        """
        order = _topological_order(self.blocks)
        
        # Add any extra blocks (including ungrouped) at the end
        all_block_names = list(order)
        for key in self.block_components:
            if key not in all_block_names:
                all_block_names.append(key)

        block_rects: Dict[str, Tuple[int, int, int, int]] = {}

        # Compute intrinsic size of each block based on its components
        block_intrinsic: Dict[str, Tuple[int, int]] = {}
        for block_name in all_block_names:
            comps = self.block_components.get(block_name, [])
            if not comps:
                block_intrinsic[block_name] = (200, 200)
                continue
            
            # Pack components in a roughly-square arrangement
            cols = max(1, int((len(comps) ** 0.5 + 0.5)))
            
            # Compute per-row heights
            rows: List[List[BaseComponent]] = []
            for i in range(0, len(comps), cols):
                rows.append(comps[i:i+cols])
            
            block_w = 0
            block_h = 0
            for row in rows:
                row_w = sum(_get_component_size(c)[0] for c in row) + COMP_SPACING * (len(row) - 1)
                row_h = max((_get_component_size(c)[1] for c in row), default=0)
                block_w = max(block_w, row_w)
                block_h += row_h + COMP_SPACING

            # Add padding
            block_w += BLOCK_PADDING * 2
            block_h += BLOCK_PADDING * 2

            block_intrinsic[block_name] = (block_w, block_h)

        # v2.4.2: FORCE single horizontal row layout for clean L-to-R flow.
        # All blocks arranged left-to-right in topological order.
        # This eliminates the vertical stacking that produced messy layouts.
        x_cursor = 0
        max_row_height = 0
        
        for name in all_block_names:
            w, h = block_intrinsic.get(name, (200, 200))
            block_rects[name] = (x_cursor, 0, w, h)
            x_cursor += w + BLOCK_SPACING
            max_row_height = max(max_row_height, h)

        return block_rects

    def place_components(
        self, block_rects: Dict[str, Tuple[int, int, int, int]]
    ) -> Dict[str, ComponentWithPos]:
        """
        Place each component within its block rect.
        Returns a dict of designator -> ComponentWithPos.
        """
        placed: Dict[str, ComponentWithPos] = {}

        for block_name, rect in block_rects.items():
            bx, by, bw, bh = rect
            comps = self.block_components.get(block_name, [])
            if not comps:
                continue

            # Pack components row by row within block
            cols = max(1, int((len(comps) ** 0.5 + 0.5)))
            x_cursor = bx + BLOCK_PADDING
            y_cursor = by + BLOCK_PADDING

            for row_idx in range(0, len(comps), cols):
                row = comps[row_idx:row_idx + cols]
                row_h = max(_get_component_size(c)[1] for c in row)

                for comp in row:
                    w, h = _get_component_size(comp)
                    pos = ComponentPos(
                        x=x_cursor,
                        y=y_cursor,
                        width=w,
                        height=h,
                        center=ElkPoint(x=x_cursor + w / 2, y=y_cursor + h / 2),
                        rotate=0.0,
                    )
                    placed[comp.designator] = ComponentWithPos(
                        **{k: v for k, v in comp.model_dump().items() if k != "pos"},
                        pos=pos,
                    )
                    x_cursor += w + COMP_SPACING

                x_cursor = bx + BLOCK_PADDING
                y_cursor += row_h + COMP_SPACING

        return placed

    def route_edges(
        self, placed: Dict[str, ComponentWithPos]
    ) -> List[ElkEdge]:
        """
        Route wires between components that share the same signal_name.
        
        v2.4.2 improvements:
        - Uses a smarter routing algorithm that prefers straight horizontal runs
        - For short connections (same block, horizontally aligned), emits direct wires
        - For longer connections, uses L-routing with proper bend points
        - SNAP endpoints to component pin positions for better wire-create success
        """
        # signal_name -> list of (designator, pin)
        signal_map: Dict[str, List[Tuple[str, any]]] = defaultdict(list)
        for designator, comp in placed.items():
            for pin in comp.pins:
                if pin.signal_name and pin.signal_name.upper() not in ("NC", "UNCONNECTED", ""):
                    signal_map[pin.signal_name].append((designator, pin))

        edges: List[ElkEdge] = []

        for signal_name, connections in signal_map.items():
            if len(connections) < 2:
                continue

            # Sort connections by x-position for cleaner routing (left to right)
            connections_sorted = sorted(
                connections,
                key=lambda c: placed.get(c[0], ComponentWithPos(
                    designator="", value="", block_name="", search_query="",
                    pins=[], part_uuid=None,
                    pos=ComponentPos(x=0, y=0, center=ElkPoint(x=0, y=0), width=0, height=0)
                )).pos.x if c[0] in placed else 0
            )

            # Star-topology: connect first (leftmost) to all others
            source_des, source_pin = connections_sorted[0]
            source_comp = placed.get(source_des)
            if not source_comp:
                continue

            for i in range(1, len(connections_sorted)):
                target_des, target_pin = connections_sorted[i]
                target_comp = placed.get(target_des)
                if not target_comp:
                    continue

                # Compute source point: right edge of source, center-y
                sx = source_comp.pos.x + source_comp.pos.width
                sy = source_comp.pos.y + source_comp.pos.height / 2

                # Compute target point: left edge of target, center-y
                tx = target_comp.pos.x
                ty = target_comp.pos.y + target_comp.pos.height / 2

                # v2.4.2: snap to straight horizontal if vertically aligned
                ALIGN_TOL = 15
                bend_points: Optional[List[ElkPoint]] = None
                
                if abs(sy - ty) <= ALIGN_TOL:
                    # Straight horizontal wire - no bends needed
                    ty = sy
                else:
                    # L-shaped route: go right from source, then vertical to target
                    mid_x = (sx + tx) / 2
                    bend_points = [
                        ElkPoint(x=mid_x, y=sy),
                        ElkPoint(x=mid_x, y=ty),
                    ]

                section_id = f"s_{signal_name}_{source_des}_{target_des}"
                section = ElkEdgeSection(
                    id=section_id,
                    startPoint=ElkPoint(x=sx, y=sy),
                    endPoint=ElkPoint(x=tx, y=ty),
                    bendPoints=bend_points,
                    incomingShape=f"{source_des}_pin_{source_pin.pin_number}",
                    outgoingShape=f"{target_des}_pin_{target_pin.pin_number}",
                )

                edge = ElkEdge(
                    sources=[f"{source_des}.{source_pin.pin_number}"],
                    targets=[f"{target_des}.{target_pin.pin_number}"],
                    container=source_comp.block_name,
                    sections=[section],
                )
                edges.append(edge)

        return edges

    def compute_block_rects(
        self,
        block_rects: Dict[str, Tuple[int, int, int, int]],
    ) -> List[BlockRect]:
        """Convert internal block rect dict to BlockRect objects.
        
        IMPORTANT: Also generates a 'block___v_root__' entry that wraps all blocks.
        The EasyEDA extension requires this root rect for positioning.
        """
        result = []
        block_desc_map = {b.name: b.description for b in self.blocks}

        # Track bounding box of all blocks for root rect
        min_x = float('inf')
        min_y = float('inf')
        max_x = float('-inf')
        max_y = float('-inf')

        for name, (x, y, w, h) in block_rects.items():
            if name == "__ungrouped__":
                continue
            
            # v2.4.2: Defensive strip of "block_" prefix to prevent duplication.
            # The LLM sometimes emits "block_Foo" in block_name; without this
            # we produce "block_block_Foo" visible in the schematic.
            clean = name[6:] if name.startswith("block_") else name
            block_name = f"block_{clean}"
            result.append(BlockRect(
                name=block_name,
                description=block_desc_map.get(name, ""),
                x=x,
                y=y,
                width=w,
                height=h,
            ))

            # Update bounding box
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x + w)
            max_y = max(max_y, y + h)

        # Add the root block rect that encompasses all blocks
        if result:
            padding = 12
            root_x = max(0, min_x - padding)
            root_y = max(0, min_y - padding)
            root_w = (max_x - root_x) + padding
            root_h = (max_y - root_y) + padding
            result.insert(0, BlockRect(
                name="block___v_root__",
                description="",
                x=root_x,
                y=root_y,
                width=root_w,
                height=root_h,
            ))

        return result

    def compute_added_nets(self, placed: Dict[str, ComponentWithPos]) -> List[AddedNet]:
        """
        Generate AddedNet entries for pins that have no wire connection.
        These become dangling net labels in the schematic.
        """
        signal_map: Dict[str, List[str]] = defaultdict(list)
        for designator, comp in placed.items():
            for pin in comp.pins:
                if pin.signal_name and pin.signal_name.upper() not in ("NC", "UNCONNECTED", ""):
                    signal_map[pin.signal_name].append(designator)

        added_nets: List[AddedNet] = []
        for designator, comp in placed.items():
            for pin in comp.pins:
                sig = pin.signal_name
                if not sig or sig.upper() in ("NC", "UNCONNECTED"):
                    continue
                connections = signal_map.get(sig, [])
                if len(connections) < 2:
                    # This signal only appears once -> it needs a net label
                    added_nets.append(AddedNet(
                        designator=designator,
                        pin_number=pin.pin_number,
                        net=sig,
                    ))
        return added_nets


def layout_circuit(circuit: CircuitStruct) -> CircuitAssembly:
    """
    Main entry point: take a CircuitStruct and return a fully laid-out CircuitAssembly.
    
    Steps:
    1. Compute block positions (horizontal left-to-right layout)
    2. Place components within blocks
    3. Route wires between shared signal names
    4. Compute block bounding rectangles
    5. Generate added_net entries for unconnected signals
    """
    engine = CircuitLayout(circuit)

    # Step 1: Block layout
    block_rects = engine.compute_block_layout()

    # Step 2: Component placement
    placed = engine.place_components(block_rects)

    # Step 3: Wire routing
    edges = engine.route_edges(placed)

    # Step 4: Block rects
    blocks_rect = engine.compute_block_rects(block_rects)

    # Step 5: Added nets (for single-connection signals -> net labels)
    added_net = engine.compute_added_nets(placed)

    # Build final assembly - sort components by designator for consistency
    components_list = sorted(placed.values(), key=lambda c: c.designator)

    return CircuitAssembly(
        metadata=circuit.metadata,
        components=components_list,
        edges=edges,
        blocks=circuit.blocks,
        blocks_rect=blocks_rect if blocks_rect else None,
        added_net=added_net if added_net else None,
        assembly_options=None,
        rm_components=None,
    )
