"""Tests for cyclic and gradient dithering algorithms."""

import numpy as np
import pytest

from full_spectrum.palette import (
    PaletteError,
    apply_cyclic,
    apply_gradient,
)


class TestApplyCyclic:
    def test_single_color(self) -> None:
        layers = np.array([0, 1, 2, 3])
        result = apply_cyclic(layers, [5])
        np.testing.assert_array_equal(result, [5, 5, 5, 5])

    def test_alternating(self) -> None:
        layers = np.array([0, 1, 2, 3, 4, 5])
        result = apply_cyclic(layers, [1, 2])
        np.testing.assert_array_equal(result, [1, 2, 1, 2, 1, 2])

    def test_triple(self) -> None:
        layers = np.array([0, 1, 2, 3, 4, 5])
        result = apply_cyclic(layers, [1, 2, 3])
        np.testing.assert_array_equal(result, [1, 2, 3, 1, 2, 3])


class TestApplyGradient:
    def test_single_stop_pair(self) -> None:
        layers = np.array([0, 1, 2, 3, 4])
        result = apply_gradient(layers, 5, [(0.0, 1), (1.0, 2)])
        # At t=0 → all color_a(1); at t=1 → all color_b(2)
        assert result[0] == 1  # t=0, ratio=0 → mono A
        assert result[-1] == 2  # t=1, ratio=1 → mono B
        # All values should be 1 or 2
        assert set(result).issubset({1, 2})

    def test_multi_stop(self) -> None:
        layers = np.array([0, 5, 9])
        result = apply_gradient(layers, 10, [(0.0, 1), (0.5, 2), (1.0, 3)])
        assert result[0] == 1  # t=0 → start of first segment, mono 1
        # t=0.5 → boundary between segments
        assert result[1] in {1, 2, 3}  # valid filament
        assert result[2] == 3  # t=1 → end of last segment, mono 3

    def test_boundary_values(self) -> None:
        # All faces at same layer → same filament
        layers = np.array([0, 0, 0])
        result = apply_gradient(layers, 1, [(0.0, 1), (1.0, 2)])
        assert np.all(result == result[0])

    def test_insufficient_stops(self) -> None:
        with pytest.raises(PaletteError, match="at least 2"):
            apply_gradient(np.array([0]), 1, [(0.0, 1)])

    def test_monotonic_gradient(self) -> None:
        """Over many layers, gradient should transition from A to B."""
        n = 100
        layers = np.arange(n)
        result = apply_gradient(layers, n, [(0.0, 1), (1.0, 2)])
        # First quarter should be mostly 1, last quarter mostly 2
        first_q = result[:n // 4]
        last_q = result[3 * n // 4:]
        assert np.sum(first_q == 1) > np.sum(first_q == 2)
        assert np.sum(last_q == 2) > np.sum(last_q == 1)
