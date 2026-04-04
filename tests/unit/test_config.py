"""Tests for palette configuration loading and validation."""

import json
from pathlib import Path

import pytest

from full_spectrum.config import (
    ConfigError,
    CyclicPalette,
    FullSpectrumConfig,
    GradientPalette,
    GradientStop,
    default_config,
    load_config,
    validate_config,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


class TestLoadConfig:
    def test_valid(self) -> None:
        config = load_config(FIXTURES / "valid_palette.json")
        assert config.layer_height_mm == 0.1
        assert config.target_format == "both"
        assert len(config.color_mappings) == 2
        assert isinstance(config.color_mappings[0].output_palette, CyclicPalette)
        assert isinstance(config.color_mappings[1].output_palette, GradientPalette)

    def test_invalid_json(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ConfigError, match="Invalid JSON"):
            load_config(bad)

    def test_missing_layer_height(self, tmp_path: Path) -> None:
        p = tmp_path / "c.json"
        p.write_text(json.dumps({"color_mappings": []}), encoding="utf-8")
        with pytest.raises(ConfigError, match="layer_height_mm"):
            load_config(p)

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="Cannot read"):
            load_config(tmp_path / "nonexistent.json")


class TestValidateConfig:
    def test_valid_no_warnings(self) -> None:
        config = load_config(FIXTURES / "valid_palette.json")
        warnings = validate_config(config)
        assert warnings == []

    def test_layer_height_out_of_range(self) -> None:
        config = FullSpectrumConfig(layer_height_mm=0.5, target_format="both", color_mappings=[])
        with pytest.raises(ConfigError, match="outside valid range"):
            validate_config(config)

    def test_layer_height_warning(self) -> None:
        config = FullSpectrumConfig(layer_height_mm=0.15, target_format="both", color_mappings=[])
        warnings = validate_config(config)
        assert any("recommended" in w for w in warnings)

    def test_filament_range(self) -> None:
        config = load_config(FIXTURES / "invalid_palette.json")
        with pytest.raises(ConfigError):
            validate_config(config)

    def test_gradient_stops_sorted(self) -> None:
        from full_spectrum.config import ColorMapping
        config = FullSpectrumConfig(
            layer_height_mm=0.1,
            target_format="both",
            color_mappings=[
                ColorMapping(
                    input_filament=1,
                    output_palette=GradientPalette(
                        stops=[GradientStop(t=0.8, filament=1), GradientStop(t=0.2, filament=2)]
                    ),
                )
            ],
        )
        with pytest.raises(ConfigError, match="not sorted"):
            validate_config(config)

    def test_gradient_stops_bounds(self) -> None:
        from full_spectrum.config import ColorMapping
        config = FullSpectrumConfig(
            layer_height_mm=0.1,
            target_format="both",
            color_mappings=[
                ColorMapping(
                    input_filament=1,
                    output_palette=GradientPalette(
                        stops=[GradientStop(t=-0.1, filament=1), GradientStop(t=1.0, filament=2)]
                    ),
                )
            ],
        )
        with pytest.raises(ConfigError, match="outside"):
            validate_config(config)


class TestDefaultConfig:
    def test_default(self) -> None:
        config = default_config(0.1)
        assert config.layer_height_mm == 0.1
        assert config.target_format == "both"
        assert len(config.color_mappings) == 1
        m = config.color_mappings[0]
        assert m.input_filament == 1
        assert isinstance(m.output_palette, CyclicPalette)
        assert m.output_palette.pattern == [1, 2]


class TestParseConfigEdgeCases:
    def test_unknown_palette_type(self, tmp_path: Path) -> None:
        cfg = {
            "layer_height_mm": 0.1,
            "color_mappings": [
                {
                    "input_filament": 1,
                    "output_palette": {"type": "unknown_type"},
                }
            ],
        }
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        with pytest.raises(ConfigError, match="Unknown palette type"):
            load_config(p)

    def test_cyclic_empty_pattern(self, tmp_path: Path) -> None:
        cfg = {
            "layer_height_mm": 0.1,
            "color_mappings": [
                {
                    "input_filament": 1,
                    "output_palette": {"type": "cyclic", "pattern": []},
                }
            ],
        }
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        with pytest.raises(ConfigError, match="non-empty"):
            load_config(p)

    def test_gradient_insufficient_stops(self, tmp_path: Path) -> None:
        cfg = {
            "layer_height_mm": 0.1,
            "color_mappings": [
                {
                    "input_filament": 1,
                    "output_palette": {"type": "gradient", "stops": [[0.0, 1]]},
                }
            ],
        }
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        with pytest.raises(ConfigError, match="at least 2 stops"):
            load_config(p)

    def test_missing_input_filament(self, tmp_path: Path) -> None:
        cfg = {
            "layer_height_mm": 0.1,
            "color_mappings": [
                {"output_palette": {"type": "cyclic", "pattern": [1, 2]}}
            ],
        }
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        with pytest.raises(ConfigError, match="missing 'input_filament'"):
            load_config(p)

    def test_missing_output_palette(self, tmp_path: Path) -> None:
        cfg = {
            "layer_height_mm": 0.1,
            "color_mappings": [{"input_filament": 1}],
        }
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        with pytest.raises(ConfigError, match="missing 'output_palette'"):
            load_config(p)


class TestValidateConfigEdgeCases:
    def test_unrecognized_target_format(self) -> None:
        config = FullSpectrumConfig(
            layer_height_mm=0.1,
            target_format="unknown_format",
            color_mappings=[],
        )
        warnings = validate_config(config)
        assert any("not recognized" in w for w in warnings)

    def test_gradient_filament_out_of_range(self) -> None:
        from full_spectrum.config import ColorMapping
        config = FullSpectrumConfig(
            layer_height_mm=0.1,
            target_format="both",
            color_mappings=[
                ColorMapping(
                    input_filament=1,
                    output_palette=GradientPalette(
                        stops=[
                            GradientStop(t=0.0, filament=1),
                            GradientStop(t=1.0, filament=99),
                        ]
                    ),
                )
            ],
        )
        with pytest.raises(ConfigError, match="filament 99"):
            validate_config(config)

    def test_cyclic_filament_out_of_range(self) -> None:
        from full_spectrum.config import ColorMapping
        config = FullSpectrumConfig(
            layer_height_mm=0.1,
            target_format="both",
            color_mappings=[
                ColorMapping(
                    input_filament=1,
                    output_palette=CyclicPalette(pattern=[1, 99]),
                )
            ],
        )
        with pytest.raises(ConfigError, match="filament 99"):
            validate_config(config)


class TestConfigBoundarySplitFields:
    def test_default_boundary_split(self) -> None:
        config = default_config(0.1)
        assert config.boundary_split is True
        assert config.max_split_depth == 9
        assert config.boundary_strategy == "bisection"

    def test_load_with_boundary_fields(self, tmp_path: Path) -> None:
        cfg = {
            "layer_height_mm": 0.1,
            "color_mappings": [],
            "boundary_split": True,
            "max_split_depth": 8,
        }
        p = tmp_path / "c.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        config = load_config(p)
        assert config.boundary_split is True
        assert config.max_split_depth == 8

    def test_validate_negative_max_split_depth(self) -> None:
        config = FullSpectrumConfig(
            layer_height_mm=0.1,
            target_format="both",
            color_mappings=[],
            max_split_depth=-1,
        )
        with pytest.raises(ConfigError, match="max_split_depth"):
            validate_config(config)

    def test_validate_high_max_split_depth_warning(self) -> None:
        config = FullSpectrumConfig(
            layer_height_mm=0.1,
            target_format="both",
            color_mappings=[],
            max_split_depth=25,
        )
        warnings = validate_config(config)
        assert any("unusually high" in w for w in warnings)

    def test_validate_invalid_boundary_strategy(self) -> None:
        config = FullSpectrumConfig(
            layer_height_mm=0.1,
            target_format="both",
            color_mappings=[],
            boundary_strategy="invalid",
        )
        with pytest.raises(ConfigError, match="boundary_strategy"):
            validate_config(config)

    def test_load_with_boundary_strategy(self, tmp_path: Path) -> None:
        cfg = {
            "layer_height_mm": 0.1,
            "color_mappings": [],
            "boundary_strategy": "geometry",
        }
        p = tmp_path / "c.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        config = load_config(p)
        assert config.boundary_strategy == "geometry"
