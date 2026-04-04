"""Utilities for parsing slicer G-code output in acceptance tests."""

from __future__ import annotations

import re

RE_LAYER_CHANGE = re.compile(r"^;\s*(?:CHANGE_LAYER|LAYER_CHANGE)\s*$", re.IGNORECASE)
RE_Z_HEIGHT = re.compile(r"^;\s*Z_HEIGHT:\s*([\d.]+)", re.IGNORECASE)
RE_Z_MOVE = re.compile(r"^G[01]\s+.*Z([\d.]+)")
RE_Z_COMMENT = re.compile(r"^;Z:([\d.]+)")
RE_TOOL = re.compile(r"^T(\d+)\s*$")

# BBL firmware uses T1000 (AMS auto) and T255 (end-of-print) as special
# commands that do not represent real filament indices.
_MAX_TOOL_INDEX = 254


def parse_gcode_tool_layers(gcode: str) -> list[tuple[float, int]]:
    """Parse G-code text and return ``(z_height, tool_index)`` per layer.

    The returned list is ordered by appearance.  The tool index reflects the
    *last* tool-change command seen before or during that layer's printing.
    """
    current_tool: int = 0
    layers: list[tuple[float, int]] = []
    layer_change_pending: bool = False

    for raw_line in gcode.splitlines():
        line = raw_line.strip()

        # Detect layer-change markers (BambuStudio / OrcaSlicer).
        if RE_LAYER_CHANGE.match(line):
            layer_change_pending = True
            continue

        # Extract Z height when a layer change is pending.
        # Prefer "; Z_HEIGHT:" comment (always correct), fall back to G-code Z moves.
        if layer_change_pending:
            zh_match = RE_Z_HEIGHT.match(line)
            if zh_match:
                z = float(zh_match.group(1))
                layer_change_pending = False
                layers.append((z, current_tool))
                continue
            z_match = RE_Z_MOVE.match(line) or RE_Z_COMMENT.match(line)
            if z_match:
                z = float(z_match.group(1))
                layer_change_pending = False
                layers.append((z, current_tool))
                continue

        # Bare tool-change command.
        tool_match = RE_TOOL.match(line)
        if tool_match:
            tool_idx = int(tool_match.group(1))
            # Ignore BBL special commands (T255=end, T1000=AMS auto).
            if tool_idx > _MAX_TOOL_INDEX:
                continue
            current_tool = tool_idx
            # Update the current layer entry if one already exists.
            if layers:
                z, _ = layers[-1]
                layers[-1] = (z, current_tool)
            continue

    return layers
