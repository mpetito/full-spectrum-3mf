"""Cyclic and gradient dithering algorithm implementations."""

from __future__ import annotations

import numpy as np


class PaletteError(Exception):
    """Raised for palette computation errors."""


def apply_cyclic(layer_indices: np.ndarray, pattern: list[int]) -> np.ndarray:
    """Apply a cyclic (repeating) palette pattern to face layer indices.
    
    Args:
        layer_indices: (n_faces,) int array of 0-based layer indices
        pattern: List of 1-based filament indices (e.g., [1, 2] for alternating)
    
    Returns:
        (n_faces,) int array of 1-based filament assignments
    """
    pat = np.array(pattern, dtype=np.int32)
    return pat[layer_indices % len(pattern)]


def compute_gradient_pattern(
    ratio: float,
    color_a: int,
    color_b: int,
    max_period: int = 8,
) -> list[int]:
    """Compute a repeating dither pattern for a blend ratio between two colors.
    
    The minority color anchors to exactly 1 layer per period;
    the majority color fills the remainder.
    
    Args:
        ratio: Blend ratio R ∈ [0.0, 1.0]. R=0 → all color_a; R=1 → all color_b.
        color_a: 1-based filament index for the "start" color
        color_b: 1-based filament index for the "end" color
        max_period: Maximum pattern period (default 8)
    
    Returns:
        List of 1-based filament indices forming the repeating pattern.
    """
    ratio = max(0.0, min(1.0, ratio))

    if ratio < 0.01:
        return [color_a]
    if ratio > 0.99:
        return [color_b]

    if ratio <= 0.5:
        minority, majority = color_b, color_a
        period = round(1.0 / ratio) if ratio > 0 else max_period
    else:
        minority, majority = color_a, color_b
        period = round(1.0 / (1.0 - ratio)) if ratio < 1 else max_period

    period = max(2, min(period, max_period))
    return [minority] + [majority] * (period - 1)


def apply_gradient(
    layer_indices: np.ndarray,
    total_layers: int,
    stops: list[tuple[float, int]],
    max_period: int = 8,
) -> np.ndarray:
    """Apply a gradient palette across face layer indices.
    
    Interpolates between gradient stops to compute blend ratios,
    then applies minority-color-anchored dither patterns.
    
    Args:
        layer_indices: (n_faces,) int array of 0-based layer indices
        total_layers: Total number of layers in the region
        stops: List of (t, filament) where t ∈ [0.0, 1.0], sorted ascending
        max_period: Maximum dither pattern period
    
    Returns:
        (n_faces,) int array of 1-based filament assignments
    """
    if len(stops) < 2:
        raise PaletteError("Gradient requires at least 2 stops")

    result = np.empty(len(layer_indices), dtype=np.int32)
    denom = max(total_layers - 1, 1)

    stop_ts = np.array([s[0] for s in stops], dtype=np.float64)
    stop_colors = np.array([s[1] for s in stops], dtype=np.int32)
    t_values = layer_indices.astype(np.float64) / denom

    # Clamp out-of-range layers to nearest stop color in bulk
    low_mask = t_values <= stop_ts[0]
    high_mask = t_values >= stop_ts[-1]
    mid_mask = ~(low_mask | high_mask)

    result[low_mask] = stop_colors[0]
    result[high_mask] = stop_colors[-1]

    if not np.any(mid_mask):
        return result

    mid_indices = np.nonzero(mid_mask)[0]
    mid_t_values = t_values[mid_mask]
    mid_layers = layer_indices[mid_mask]

    # Vectorized segment selection for all in-range faces
    segment_indices = np.searchsorted(stop_ts, mid_t_values, side="right") - 1
    segment_indices = np.clip(segment_indices, 0, len(stop_ts) - 2)

    # Process in bulk per segment, then per unique layer within the segment
    for seg_idx in np.unique(segment_indices):
        seg_mask = segment_indices == seg_idx
        seg_face_indices = mid_indices[seg_mask]
        seg_layers = mid_layers[seg_mask]

        t0 = stop_ts[seg_idx]
        t1 = stop_ts[seg_idx + 1]
        c0 = int(stop_colors[seg_idx])
        c1 = int(stop_colors[seg_idx + 1])
        span = t1 - t0

        unique_layers, inverse = np.unique(seg_layers, return_inverse=True)

        if span > 1e-9:
            local_t_values = (unique_layers.astype(np.float64) / denom - t0) / span
        else:
            local_t_values = np.zeros(len(unique_layers), dtype=np.float64)

        unique_assignments = np.empty(len(unique_layers), dtype=np.int32)
        for u_idx, (layer, local_t) in enumerate(zip(unique_layers, local_t_values)):
            pattern = compute_gradient_pattern(float(local_t), c0, c1, max_period)
            unique_assignments[u_idx] = pattern[int(layer) % len(pattern)]

        result[seg_face_indices] = unique_assignments[inverse]

    return result
