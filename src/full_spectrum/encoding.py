"""Filament hex encode/decode for 3MF per-triangle attributes."""

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
