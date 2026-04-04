"""Tests for G-code tool-layer parser utility."""

from textwrap import dedent

from tests.acceptance.gcode_utils import parse_gcode_tool_layers


class TestBambuStudioFormat:
    """BambuStudio-style G-code with ``; CHANGE_LAYER`` markers."""

    def test_basic_layer_tool_sequence(self) -> None:
        gcode = dedent("""\
            ; CHANGE_LAYER
            G1 Z0.200 F600
            T0
            G1 X10 Y10
            ; CHANGE_LAYER
            G1 Z0.400 F600
            T1
            G1 X20 Y20
        """)
        assert parse_gcode_tool_layers(gcode) == [(0.2, 0), (0.4, 1)]

    def test_tool_persists_across_layers(self) -> None:
        gcode = dedent("""\
            ; CHANGE_LAYER
            G1 Z0.200 F600
            T1
            G1 X10
            ; CHANGE_LAYER
            G1 Z0.400 F600
            G1 X20
        """)
        assert parse_gcode_tool_layers(gcode) == [(0.2, 1), (0.4, 1)]

    def test_g0_rapid_z_move(self) -> None:
        gcode = dedent("""\
            ; CHANGE_LAYER
            G0 Z0.300 F600
            T0
            G1 X10
        """)
        assert parse_gcode_tool_layers(gcode) == [(0.3, 0)]


class TestOrcaSlicerFormat:
    """OrcaSlicer-style G-code with ``;LAYER_CHANGE`` and ``;Z:`` markers."""

    def test_basic_orca_format(self) -> None:
        gcode = dedent("""\
            ;LAYER_CHANGE
            ;Z:0.2
            T0
            G1 X10
            ;LAYER_CHANGE
            ;Z:0.4
            T1
            G1 X20
        """)
        assert parse_gcode_tool_layers(gcode) == [(0.2, 0), (0.4, 1)]

    def test_orca_tool_before_layer(self) -> None:
        gcode = dedent("""\
            T1
            ;LAYER_CHANGE
            ;Z:0.2
            G1 X10
        """)
        assert parse_gcode_tool_layers(gcode) == [(0.2, 1)]


class TestEdgeCases:
    """Edge cases and larger sequences."""

    def test_default_tool_is_t0(self) -> None:
        gcode = dedent("""\
            ; CHANGE_LAYER
            G1 Z0.200 F600
            G1 X10
        """)
        assert parse_gcode_tool_layers(gcode) == [(0.2, 0)]

    def test_empty_gcode(self) -> None:
        assert parse_gcode_tool_layers("") == []

    def test_alternating_20_layers(self) -> None:
        lines: list[str] = []
        expected: list[tuple[float, int]] = []
        for i in range(20):
            z = round(0.2 * (i + 1), 1)
            tool = i % 2
            lines.append("; CHANGE_LAYER")
            lines.append(f"G1 Z{z:.3f} F600")
            lines.append(f"T{tool}")
            lines.append("G1 X10 Y10")
            expected.append((z, tool))

        assert parse_gcode_tool_layers("\n".join(lines)) == expected

    def test_three_step_cycle(self) -> None:
        cycle = [0, 0, 1]
        lines: list[str] = []
        expected: list[tuple[float, int]] = []
        for i in range(6):
            z = round(0.2 * (i + 1), 1)
            tool = cycle[i % len(cycle)]
            lines.append("; CHANGE_LAYER")
            lines.append(f"G1 Z{z:.3f} F600")
            lines.append(f"T{tool}")
            lines.append("G1 X10")
            expected.append((z, tool))

        assert parse_gcode_tool_layers("\n".join(lines)) == expected

    def test_tool_change_after_z_in_same_layer(self) -> None:
        gcode = dedent("""\
            ; CHANGE_LAYER
            G1 Z0.200 F600
            G1 X10
            T1
            G1 X20
            ; CHANGE_LAYER
            G1 Z0.400 F600
            T0
            G1 X30
        """)
        assert parse_gcode_tool_layers(gcode) == [(0.2, 1), (0.4, 0)]

    def test_bbl_special_tools_ignored(self) -> None:
        """T255 (end-of-print) and T1000 (AMS auto) are ignored."""
        gcode = dedent("""\
            T1000
            ; CHANGE_LAYER
            G1 Z0.200 F600
            T0
            G1 X10
            ; CHANGE_LAYER
            G1 Z0.400 F600
            T1
            G1 X20
            T255
        """)
        assert parse_gcode_tool_layers(gcode) == [(0.2, 0), (0.4, 1)]

    def test_z_height_comment_preferred_over_travel_z(self) -> None:
        """BambuStudio emits Z_HEIGHT comment right after CHANGE_LAYER.

        The parser should use this rather than a later travel-height G1 Z move.
        """
        gcode = dedent("""\
            ; CHANGE_LAYER
            ; Z_HEIGHT: 0.2
            ; LAYER_HEIGHT: 0.2
            G1 Z.6 F30000
            T0
            G1 X10
            ; CHANGE_LAYER
            ; Z_HEIGHT: 0.3
            ; LAYER_HEIGHT: 0.1
            T1
            G1 X20
        """)
        assert parse_gcode_tool_layers(gcode) == [(0.2, 0), (0.3, 1)]

    def test_real_bambu_layer_sequence(self) -> None:
        """Realistic BambuStudio G-code with startup, tool changes between layers."""
        gcode = dedent("""\
            T1000
            T0
            G1 Z5 F1200
            G1 Z0.8 F1200
            ; CHANGE_LAYER
            ; Z_HEIGHT: 0.2
            ; LAYER_HEIGHT: 0.2
            G1 Z.6 F30000
            T0
            G1 X10
            ; CHANGE_LAYER
            ; Z_HEIGHT: 0.3
            ; LAYER_HEIGHT: 0.1
            G1 Z3.3 F1200
            T1
            G1 Z3.3 F3000
            G1 Z.3
            G1 X20
            ; CHANGE_LAYER
            ; Z_HEIGHT: 0.4
            ; LAYER_HEIGHT: 0.1
            G1 Z3.4 F1200
            T0
            G1 Z3.4 F3000
            G1 Z.4
            G1 X30
            T255
        """)
        assert parse_gcode_tool_layers(gcode) == [
            (0.2, 0), (0.3, 1), (0.4, 0),
        ]
