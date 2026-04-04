from __future__ import annotations

from pathlib import Path

import pytest

from tests.acceptance.gcode_utils import parse_gcode_tool_layers

pytestmark = pytest.mark.slicer

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_alternating_tools(
    layers: list[tuple[float, int]],
    *,
    min_layers: int,
) -> None:
    """Assert layers show a strict alternating T0/T1 pattern."""
    assert len(layers) >= min_layers, (
        f"Expected at least {min_layers} layers, got {len(layers)}"
    )
    tools = [t for _, t in layers]
    tools_used = set(tools)
    assert tools_used == {0, 1}, (
        f"Expected tools {{0, 1}}, got {tools_used}"
    )
    for i in range(1, len(tools)):
        assert tools[i] != tools[i - 1], (
            f"Layer {i} (Z={layers[i][0]}) has same tool T{tools[i]} "
            f"as layer {i - 1} (Z={layers[i - 1][0]})"
        )


# ---------------------------------------------------------------------------
# Fixture-based slicer validation
# ---------------------------------------------------------------------------

class TestSingleColorFixture:
    """Single-color fixture should produce only T0 — no tool changes."""

    def test_single_color_no_tool_changes(self, slice_3mf):
        fixture = FIXTURES_DIR / "cube-10-10-4-0.1-single-color.3mf"
        assert fixture.exists(), f"Missing fixture: {fixture}"

        gcode = slice_3mf(fixture)
        layers = parse_gcode_tool_layers(gcode)

        assert len(layers) >= 30, (
            f"Expected ≥30 layers for 4mm cube at 0.1mm, got {len(layers)}"
        )
        tools_used = {t for _, t in layers}
        assert tools_used == {0}, (
            f"Single-color fixture should only use T0, got tools: {tools_used}"
        )


class TestDualColorFixture:
    """Dual-color fixture should produce alternating T0/T1 tool changes."""

    def test_dual_color_alternating(self, slice_3mf):
        fixture = FIXTURES_DIR / "cube-10-10-4-0.1-dual-color.3mf"
        assert fixture.exists(), f"Missing fixture: {fixture}"

        gcode = slice_3mf(fixture)
        layers = parse_gcode_tool_layers(gcode)

        # 4mm cube, 0.2mm first layer + 0.1mm subsequent ≈ 39 layers
        _assert_alternating_tools(layers, min_layers=30)

    def test_dual_color_layer_count(self, slice_3mf):
        fixture = FIXTURES_DIR / "cube-10-10-4-0.1-dual-color.3mf"
        gcode = slice_3mf(fixture)
        layers = parse_gcode_tool_layers(gcode)

        # Expect ~39 layers (0.2mm first + 38×0.1mm = 4.0mm)
        assert 35 <= len(layers) <= 45, (
            f"Expected ~39 layers, got {len(layers)}"
        )
