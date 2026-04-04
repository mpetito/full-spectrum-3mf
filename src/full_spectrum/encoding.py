"""Filament hex encode/decode for 3MF per-triangle attributes."""

from __future__ import annotations

from dataclasses import dataclass

MAX_FILAMENTS = 10

# 1-based filament index → hex string (whole-triangle; low 2 bits = 00)
FILAMENT_HEX_TABLE: dict[int, str] = {
    1: "4", 2: "8", 3: "0C", 4: "1C", 5: "2C",
    6: "3C", 7: "4C", 8: "5C", 9: "6C", 10: "7C",
}

# Reverse: uppercase hex string → 1-based filament
HEX_FILAMENT_TABLE: dict[str, int] = {v.upper(): k for k, v in FILAMENT_HEX_TABLE.items()}


def hex_to_filament(hex_str: str) -> int:
    """Decode mmu_segmentation/paint_color hex to 1-based filament index.

    Raises ValueError for sub-painted triangles (len > 2) or unknown codes.
    """
    normalized = hex_str.strip().upper()
    if len(normalized) > 2:
        raise ValueError(f"Sub-painted triangle detected: {hex_str!r}")
    filament = HEX_FILAMENT_TABLE.get(normalized)
    if filament is None:
        raise ValueError(f"Invalid filament hex code: {hex_str!r}")
    return filament


def filament_to_hex(filament: int) -> str:
    """Encode 1-based filament index to hex string for 3MF attributes.

    Raises ValueError for out-of-range filament (must be 1–10).
    """
    hex_str = FILAMENT_HEX_TABLE.get(filament)
    if hex_str is None:
        raise ValueError(f"Filament index {filament} out of range (must be 1–10)")
    return hex_str


def is_sub_painted(hex_str: str) -> bool:
    """Return True if the hex string indicates sub-triangle painting (recursive bisection)."""
    return len(hex_str.strip()) > 2


# ---------------------------------------------------------------------------
# Bisection tree data structures & codec
# ---------------------------------------------------------------------------


@dataclass
class BisectionNode:
    """Base for recursive bisection tree nodes."""


@dataclass
class LeafNode(BisectionNode):
    """Leaf: no children, represents a triangle region with a single filament state."""

    state: int  # 0=default, 1=ext1, 2=ext2, ..., 15=ext15

    def __post_init__(self) -> None:
        if not 0 <= self.state <= 15:
            raise ValueError(f"LeafNode state must be 0–15, got {self.state}")


@dataclass
class SplitNode(BisectionNode):
    """Interior split node representing a 1-, 2-, or 3-split subdivision."""

    split_sides: int  # Number of split sides encoded by this node
    special_side: int  # Edge index that IS split: 0=v0→v1, 1=v1→v2, 2=v2→v0
    children: list[BisectionNode]  # Child nodes; length must be split_sides + 1

    def __post_init__(self) -> None:
        if self.special_side not in (0, 1, 2):
            raise ValueError(
                f"SplitNode special_side must be 0–2, got {self.special_side}"
            )
        expected = self.split_sides + 1
        if len(self.children) != expected:
            raise ValueError(
                f"SplitNode with split_sides={self.split_sides} expects "
                f"{expected} children, got {len(self.children)}"
            )


def _collect_nibbles(node: BisectionNode, nibbles: list[int]) -> None:
    """DFS-collect 4-bit nibbles for *node* into *nibbles* (encode helper)."""
    if isinstance(node, LeafNode):
        if node.state <= 2:
            nibbles.append(node.state << 2)  # simple leaf: (state << 2) | 0
        else:
            nibbles.append(0xC)  # sentinel nibble: xx=11, yy=00
            nibbles.append(node.state - 3)  # extended state payload
    elif isinstance(node, SplitNode):
        nibbles.append((node.special_side << 2) | node.split_sides)
        for child in reversed(node.children):
            _collect_nibbles(child, nibbles)
    else:
        raise TypeError(f"Unknown node type: {type(node)}")


HEX_CHARS = "0123456789ABCDEF"


def encode_bisection_tree(node: BisectionNode) -> str:
    """Encode a bisection tree to a PrusaSlicer-compatible hex string.

    The hex string is reversed: root is the rightmost character.
    """
    nibbles: list[int] = []
    _collect_nibbles(node, nibbles)
    # Build reversed: nibbles are in DFS order, hex string is reversed
    chars = [HEX_CHARS[nib] for nib in reversed(nibbles)]
    return "".join(chars)


def decode_bisection_tree(hex_str: str) -> BisectionNode:
    """Decode a PrusaSlicer hex string into a bisection tree.

    Reads right-to-left; root is the rightmost character.
    Raises ValueError for malformed input.
    """
    if not hex_str:
        raise ValueError("Empty hex string")
    chars = list(hex_str.upper())
    pos = len(chars) - 1  # start from rightmost (root)
    max_depth = min(len(chars) * 4, 500)  # cap recursion for malicious input
    depth = 0

    def _read() -> BisectionNode:
        nonlocal pos, depth
        depth += 1
        if depth > max_depth:
            raise ValueError(f"Tree too deep (>{max_depth}); possibly malformed input")
        if pos < 0:
            raise ValueError("Unexpected end of hex string while decoding")
        nibble = int(chars[pos], 16)
        pos -= 1

        yy = nibble & 0x03
        xx = (nibble >> 2) & 0x03

        if yy == 0:
            # Leaf
            if xx == 3:
                # Extended state sentinel — next nibble is state-3
                if pos < 0:
                    raise ValueError(
                        "Unexpected end of hex string reading extended state"
                    )
                ext_nibble = int(chars[pos], 16)
                pos -= 1
                return LeafNode(state=ext_nibble + 3)
            return LeafNode(state=xx)

        # Split node
        split_sides = yy
        special_side = xx
        num_children = split_sides + 1
        # Children are read in reverse order (last child first)
        children: list[BisectionNode] = []
        for _ in range(num_children):
            children.append(_read())
        children.reverse()
        return SplitNode(
            split_sides=split_sides,
            special_side=special_side,
            children=children,
        )

    root = _read()
    if pos >= 0:
        raise ValueError(
            f"Trailing data after decoding: {hex_str[:pos + 1]!r}"
        )
    return root
