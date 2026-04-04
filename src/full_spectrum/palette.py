"""Cyclic and gradient dithering algorithm implementations.

Gradient dithering uses sequential error diffusion to distribute
minority-color layers maximally apart, eliminating structural banding.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


class PaletteError(Exception):
    """Raised for palette computation errors."""


def apply_cyclic(layer_indices: np.ndarray, pattern: list[int] | tuple[int, ...]) -> np.ndarray:
    """Apply a cyclic (repeating) palette pattern to face layer indices.
    
    Args:
        layer_indices: (n_faces,) int array of 0-based layer indices
        pattern: Sequence of 1-based filament indices (e.g., [1, 2] for alternating)
    
    Returns:
        (n_faces,) int array of 1-based filament assignments
    """
    pat = np.array(pattern, dtype=np.int32)
    return pat[layer_indices % len(pattern)]


def build_gradient_layer_map(
    total_layers: int,
    stops: Sequence[tuple[float, int]],
) -> np.ndarray:
    """Build a complete layer→filament map using sequential error diffusion.

    Processes layers sequentially so the error accumulator carries across
    segment boundaries, eliminating phase-alignment artifacts and the
    minority/majority role-swap discontinuity at ratio=0.5.

    Args:
        total_layers: Total number of layers
        stops: Sequence of (t, filament) sorted ascending by t

    Returns:
        (total_layers,) int array of 1-based filament assignments
    """
    layer_map = np.empty(total_layers, dtype=np.int32)
    denom = max(total_layers - 1, 1)

    stop_ts = [s[0] for s in stops]
    stop_colors = [s[1] for s in stops]
    n_stops = len(stops)

    error = 0.0

    for layer in range(total_layers):
        t = layer / denom

        # At or before first stop
        if t <= stop_ts[0]:
            layer_map[layer] = stop_colors[0]
            continue
        # At or after last stop
        if t >= stop_ts[-1]:
            layer_map[layer] = stop_colors[-1]
            continue

        # Find segment
        seg = 0
        for s in range(n_stops - 2, -1, -1):
            if t >= stop_ts[s]:
                seg = s
                break

        c0, c1 = stop_colors[seg], stop_colors[seg + 1]
        span = stop_ts[seg + 1] - stop_ts[seg]

        if span < 1e-9 or c0 == c1:
            layer_map[layer] = c0
            continue

        # ratio = fraction of c1 at this position
        ratio = (t - stop_ts[seg]) / span

        # Error diffusion
        error += ratio
        if error >= 0.5:
            layer_map[layer] = c1
            error -= 1.0
        else:
            layer_map[layer] = c0

    return layer_map


def apply_gradient(
    layer_indices: np.ndarray,
    total_layers: int,
    stops: Sequence[tuple[float, int]],
) -> np.ndarray:
    """Apply a gradient palette across face layer indices.
    
    Uses sequential error diffusion to distribute color transitions
    maximally apart, eliminating structural banding artifacts.
    
    Args:
        layer_indices: (n_faces,) int array of 0-based layer indices
        total_layers: Total number of layers in the region
        stops: Sequence of (t, filament) where t ∈ [0.0, 1.0], sorted ascending
    
    Returns:
        (n_faces,) int array of 1-based filament assignments
    """
    if len(stops) < 2:
        raise PaletteError("Gradient requires at least 2 stops")

    # Build the full sequential layer map with error diffusion
    layer_map = build_gradient_layer_map(total_layers, stops)

    # Look up each face's layer in the pre-built map
    clamped = np.clip(layer_indices, 0, total_layers - 1)
    return layer_map[clamped]
