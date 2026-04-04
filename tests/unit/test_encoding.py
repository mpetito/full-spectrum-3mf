"""Tests for filament hex encoding/decoding."""

import pytest

from full_spectrum.encoding import (
    BisectionNode,
    FILAMENT_HEX_TABLE,
    LeafNode,
    SplitNode,
    decode_bisection_tree,
    encode_bisection_tree,
    filament_to_hex,
    hex_to_filament,
    is_sub_painted,
)


class TestHexToFilament:
    @pytest.mark.parametrize(
        "hex_str,expected",
        [(v, k) for k, v in FILAMENT_HEX_TABLE.items()],
    )
    def test_valid_all_values(self, hex_str: str, expected: int) -> None:
        assert hex_to_filament(hex_str) == expected

    @pytest.mark.parametrize("hex_str", ["0c", "1c", "2c", "3c", "4c", "5c", "6c", "7c"])
    def test_case_insensitive(self, hex_str: str) -> None:
        result = hex_to_filament(hex_str)
        assert result == hex_to_filament(hex_str.upper())

    def test_sub_painted_rejection(self) -> None:
        with pytest.raises(ValueError, match="Sub-painted"):
            hex_to_filament("0C1C2C")

    def test_unknown_code(self) -> None:
        with pytest.raises(ValueError, match="Invalid filament hex code"):
            hex_to_filament("FF")


class TestFilamentToHex:
    @pytest.mark.parametrize("filament", range(1, 11))
    def test_roundtrip(self, filament: int) -> None:
        assert hex_to_filament(filament_to_hex(filament)) == filament

    @pytest.mark.parametrize("filament", [0, 11, -1, 100])
    def test_out_of_range(self, filament: int) -> None:
        with pytest.raises(ValueError, match="out of range"):
            filament_to_hex(filament)


class TestIsSubPainted:
    @pytest.mark.parametrize("hex_str,expected", [
        ("4", False), ("8", False), ("0C", False),
        ("0C1C", True), ("0C1C2C", True),
    ])
    def test_detection(self, hex_str: str, expected: bool) -> None:
        assert is_sub_painted(hex_str) == expected


# ---------------------------------------------------------------------------
# Bisection tree dataclasses
# ---------------------------------------------------------------------------


class TestBisectionTreeDataclasses:
    def test_leaf_node_construction(self) -> None:
        leaf = LeafNode(state=1)
        assert leaf.state == 1

    def test_leaf_node_default_state(self) -> None:
        leaf = LeafNode(state=0)
        assert leaf.state == 0

    def test_leaf_node_max_state(self) -> None:
        leaf = LeafNode(state=15)
        assert leaf.state == 15

    def test_leaf_node_invalid_state_negative(self) -> None:
        with pytest.raises(ValueError, match="0–15"):
            LeafNode(state=-1)

    def test_leaf_node_invalid_state_too_high(self) -> None:
        with pytest.raises(ValueError, match="0–15"):
            LeafNode(state=16)

    def test_leaf_node_equality(self) -> None:
        assert LeafNode(1) == LeafNode(1)
        assert LeafNode(1) != LeafNode(2)

    def test_split_node_construction(self) -> None:
        node = SplitNode(
            split_sides=1, special_side=0, children=[LeafNode(1), LeafNode(2)]
        )
        assert node.split_sides == 1
        assert node.special_side == 0
        assert len(node.children) == 2

    def test_split_node_invalid_special_side(self) -> None:
        with pytest.raises(ValueError, match="special_side"):
            SplitNode(split_sides=1, special_side=3, children=[LeafNode(0), LeafNode(0)])

    def test_split_node_wrong_child_count(self) -> None:
        with pytest.raises(ValueError, match="children"):
            SplitNode(split_sides=1, special_side=0, children=[LeafNode(0)])

    def test_is_bisection_node(self) -> None:
        assert isinstance(LeafNode(0), BisectionNode)
        assert isinstance(
            SplitNode(1, 0, [LeafNode(0), LeafNode(0)]), BisectionNode
        )


# ---------------------------------------------------------------------------
# Encode bisection tree
# ---------------------------------------------------------------------------


WORKED_EXAMPLES: list[tuple[str, BisectionNode, str]] = [
    ("Whole triangle Ext1", LeafNode(1), "4"),
    ("Whole triangle Ext2", LeafNode(2), "8"),
    ("Whole triangle default", LeafNode(0), "0"),
    ("Whole triangle Ext3 (extended)", LeafNode(3), "0C"),
    ("Whole triangle Ext15", LeafNode(15), "CC"),
    (
        "1-split edge 0 [Ext1, Ext2]",
        SplitNode(1, 0, [LeafNode(1), LeafNode(2)]),
        "481",
    ),
    (
        "1-split edge 1 [Ext1, Ext2]",
        SplitNode(1, 1, [LeafNode(1), LeafNode(2)]),
        "485",
    ),
    (
        "1-split edge 2 [Ext1, Ext2]",
        SplitNode(1, 2, [LeafNode(1), LeafNode(2)]),
        "489",
    ),
    (
        "Nested 2-level",
        SplitNode(
            1,
            0,
            [
                LeafNode(1),
                SplitNode(1, 1, [LeafNode(1), LeafNode(2)]),
            ],
        ),
        "44851",
    ),
    (
        "2-split edge 0 [Ext1, Ext2, default]",
        SplitNode(2, 0, [LeafNode(1), LeafNode(2), LeafNode(0)]),
        "4802",
    ),
    (
        "2-split edge 1 [Ext1, Ext2, default]",
        SplitNode(2, 1, [LeafNode(1), LeafNode(2), LeafNode(0)]),
        "4806",
    ),
    (
        "2-split edge 2 [Ext1, Ext2, default]",
        SplitNode(2, 2, [LeafNode(1), LeafNode(2), LeafNode(0)]),
        "480A",
    ),
    (
        "3-split [Ext1, Ext2, default, Ext1]",
        SplitNode(3, 0, [LeafNode(1), LeafNode(2), LeafNode(0), LeafNode(1)]),
        "48043",
    ),
]


class TestEncodeBisectionTree:
    @pytest.mark.parametrize(
        "desc,tree,expected_hex",
        WORKED_EXAMPLES,
        ids=[e[0] for e in WORKED_EXAMPLES],
    )
    def test_worked_examples(
        self, desc: str, tree: BisectionNode, expected_hex: str
    ) -> None:
        assert encode_bisection_tree(tree) == expected_hex

    @pytest.mark.parametrize("state", range(3, 16))
    def test_extended_states(self, state: int) -> None:
        tree = LeafNode(state)
        hex_str = encode_bisection_tree(tree)
        # Extended leaves produce 2 hex chars: sentinel 0xC then (state - 3)
        assert len(hex_str) == 2
        assert hex_str[1] == "C"  # sentinel is rightmost in reversed string

    @pytest.mark.parametrize("edge", [0, 1, 2])
    def test_all_edge_indices(self, edge: int) -> None:
        tree = SplitNode(1, edge, [LeafNode(0), LeafNode(0)])
        hex_str = encode_bisection_tree(tree)
        # Root nibble should be (edge << 2) | 1
        root_nibble = int(hex_str[-1], 16)
        assert root_nibble == (edge << 2) | 1


# ---------------------------------------------------------------------------
# Decode bisection tree
# ---------------------------------------------------------------------------


class TestDecodeBisectionTree:
    @pytest.mark.parametrize(
        "desc,expected_tree,hex_str",
        WORKED_EXAMPLES,
        ids=[e[0] for e in WORKED_EXAMPLES],
    )
    def test_worked_examples(
        self, desc: str, expected_tree: BisectionNode, hex_str: str
    ) -> None:
        assert decode_bisection_tree(hex_str) == expected_tree

    @pytest.mark.parametrize("state", range(3, 16))
    def test_extended_states(self, state: int) -> None:
        hex_str = encode_bisection_tree(LeafNode(state))
        assert decode_bisection_tree(hex_str) == LeafNode(state)

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="Empty"):
            decode_bisection_tree("")

    def test_trailing_data_raises(self) -> None:
        # "40" = a leaf "0" followed by trailing "4"
        with pytest.raises(ValueError, match="Trailing"):
            decode_bisection_tree("40")


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestBisectionRoundTrip:
    @pytest.mark.parametrize(
        "desc,tree,hex_str",
        WORKED_EXAMPLES,
        ids=[e[0] for e in WORKED_EXAMPLES],
    )
    def test_encode_decode(
        self, desc: str, tree: BisectionNode, hex_str: str
    ) -> None:
        assert decode_bisection_tree(encode_bisection_tree(tree)) == tree

    @pytest.mark.parametrize(
        "desc,tree,hex_str",
        WORKED_EXAMPLES,
        ids=[e[0] for e in WORKED_EXAMPLES],
    )
    def test_decode_encode(
        self, desc: str, tree: BisectionNode, hex_str: str
    ) -> None:
        assert encode_bisection_tree(decode_bisection_tree(hex_str)) == hex_str

    def test_deep_nested_roundtrip(self) -> None:
        """3-level deep tree round-trips correctly."""
        tree = SplitNode(
            1,
            2,
            [
                SplitNode(
                    1,
                    0,
                    [LeafNode(0), LeafNode(5)],
                ),
                SplitNode(
                    1,
                    1,
                    [LeafNode(1), LeafNode(2)],
                ),
            ],
        )
        hex_str = encode_bisection_tree(tree)
        assert decode_bisection_tree(hex_str) == tree
