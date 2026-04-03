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

    for idx in range(len(layer_indices)):
        layer = layer_indices[idx]
        t = layer / denom

        # Clamp t to stop range so out-of-range layers get nearest stop
        t_min = stops[0][0]
        t_max = stops[-1][0]
        if t <= t_min:
            result[idx] = stops[0][1]
            continue
        if t >= t_max:
            result[idx] = stops[-1][1]
            continue

        # Find enclosing stop pair
        filament = stops[-1][1]  # fallback to last stop
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t0 <= t <= t1:
                span = t1 - t0
                local_t = (t - t0) / span if span > 1e-9 else 0.0
                pattern = compute_gradient_pattern(local_t, c0, c1, max_period)
                filament = pattern[layer % len(pattern)]
                break

        result[idx] = filament

    return result
