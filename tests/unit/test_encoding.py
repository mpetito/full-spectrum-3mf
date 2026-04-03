"""Tests for filament hex encoding/decoding."""

import pytest

from full_spectrum.encoding import (
    FILAMENT_HEX_TABLE,
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
