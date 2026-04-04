"""JSON palette configuration loading and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    """Raised for invalid configuration."""


@dataclass(frozen=True)
class CyclicPalette:
    """Repeating sequence of filament slot indices."""
    pattern: list[int]
    type: str = field(default="cyclic", init=False)


@dataclass(frozen=True)
class GradientStop:
    """A single gradient stop: position t ∈ [0.0, 1.0] and filament index."""
    t: float
    filament: int


@dataclass(frozen=True)
class GradientPalette:
    """Frequency-modulated gradient with minority-color anchoring."""
    stops: list[GradientStop]
    max_period: int = 8
    type: str = field(default="gradient", init=False)


@dataclass(frozen=True)
class ColorMapping:
    """Maps an input filament to an output dithering palette."""
    input_filament: int
    output_palette: CyclicPalette | GradientPalette


@dataclass(frozen=True)
class FullSpectrumConfig:
    """Top-level configuration for the Full Spectrum pipeline."""
    layer_height_mm: float
    target_format: str
    color_mappings: list[ColorMapping]
    boundary_split: bool = True
    max_split_depth: int = 9
    boundary_strategy: str = "bisection"


def _parse_palette(data: dict) -> CyclicPalette | GradientPalette:
    """Parse a palette dict into a CyclicPalette or GradientPalette."""
    palette_type = data.get("type")
    if palette_type == "cyclic":
        pattern = data.get("pattern")
        if not isinstance(pattern, list) or not pattern:
            raise ConfigError("Cyclic palette requires non-empty 'pattern' list")
        return CyclicPalette(pattern=pattern)
    elif palette_type == "gradient":
        raw_stops = data.get("stops")
        if not isinstance(raw_stops, list) or len(raw_stops) < 2:
            raise ConfigError("Gradient palette requires at least 2 stops")
        stops = []
        for i, s in enumerate(raw_stops):
            if not isinstance(s, list) or len(s) != 2:
                raise ConfigError(
                    f"Gradient stop {i} must be in format [t, filament]"
                )
            stops.append(GradientStop(t=s[0], filament=s[1]))
        max_period = data.get("max_period", 8)
        return GradientPalette(stops=stops, max_period=max_period)
    else:
        raise ConfigError(f"Unknown palette type: {palette_type!r}")


def load_config(path: str | Path) -> FullSpectrumConfig:
    """Load and parse a JSON palette configuration file.

    Raises ConfigError for parse errors or missing required fields.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in {path}: {e}") from e
    except OSError as e:
        raise ConfigError(f"Cannot read config {path}: {e}") from e

    layer_height = raw.get("layer_height_mm")
    if layer_height is None:
        raise ConfigError("Missing required field: 'layer_height_mm'")

    target_format = raw.get("target_format", "both")

    mappings = []
    for i, cm in enumerate(raw.get("color_mappings", [])):
        input_fil = cm.get("input_filament")
        if input_fil is None:
            raise ConfigError(f"color_mappings[{i}]: missing 'input_filament'")
        palette_data = cm.get("output_palette")
        if palette_data is None:
            raise ConfigError(f"color_mappings[{i}]: missing 'output_palette'")
        try:
            palette = _parse_palette(palette_data)
        except ConfigError as e:
            raise ConfigError(f"color_mappings[{i}]: {e}") from e
        mappings.append(ColorMapping(input_filament=input_fil, output_palette=palette))

    return FullSpectrumConfig(
        layer_height_mm=layer_height,
        target_format=target_format,
        color_mappings=mappings,
        boundary_split=raw.get("boundary_split", True),
        max_split_depth=raw.get("max_split_depth", 9),
        boundary_strategy=raw.get("boundary_strategy", "bisection"),
    )


def validate_config(config: FullSpectrumConfig) -> list[str]:
    """Validate config, raising ConfigError for errors, returning warnings list."""
    warnings: list[str] = []

    # boundary_strategy
    if config.boundary_strategy not in {"bisection", "geometry"}:
        raise ConfigError(
            f"boundary_strategy must be 'bisection' or 'geometry', got {config.boundary_strategy!r}"
        )

    # max_split_depth
    if config.max_split_depth < 0:
        raise ConfigError("max_split_depth must be non-negative")
    if config.max_split_depth > 20:
        warnings.append(f"max_split_depth {config.max_split_depth} is unusually high (>20)")

    # Layer height range
    if not (0.04 <= config.layer_height_mm <= 0.2):
        raise ConfigError(
            f"layer_height_mm {config.layer_height_mm} outside valid range [0.04, 0.2]"
        )
    if not (0.08 <= config.layer_height_mm <= 0.12):
        warnings.append(
            f"layer_height_mm {config.layer_height_mm} outside recommended range [0.08, 0.12]"
        )

    # Target format
    if config.target_format not in {"prusaslicer", "bambu", "both"}:
        warnings.append(
            f"target_format {config.target_format!r} not recognized; expected 'prusaslicer', 'bambu', or 'both'"
        )

    # Color mappings
    for i, cm in enumerate(config.color_mappings):
        if not (1 <= cm.input_filament <= 10):
            raise ConfigError(
                f"color_mappings[{i}]: input_filament {cm.input_filament} outside range [1, 10]"
            )

        palette = cm.output_palette
        if isinstance(palette, CyclicPalette):
            for j, f in enumerate(palette.pattern):
                if not (1 <= f <= 10):
                    raise ConfigError(
                        f"color_mappings[{i}].pattern[{j}]: filament {f} outside range [1, 10]"
                    )
        elif isinstance(palette, GradientPalette):
            # Stops sorted by t
            for j in range(1, len(palette.stops)):
                if palette.stops[j].t < palette.stops[j - 1].t:
                    raise ConfigError(
                        f"color_mappings[{i}]: gradient stops not sorted by t"
                    )
            # Stops within [0, 1]
            for j, stop in enumerate(palette.stops):
                if not (0.0 <= stop.t <= 1.0):
                    raise ConfigError(
                        f"color_mappings[{i}].stops[{j}]: t={stop.t} outside [0.0, 1.0]"
                    )
                if not (1 <= stop.filament <= 10):
                    raise ConfigError(
                        f"color_mappings[{i}].stops[{j}]: filament {stop.filament} outside range [1, 10]"
                    )

    return warnings


def default_config(layer_height: float, target_format: str = "both") -> FullSpectrumConfig:
    """Create a default config with cyclic [1, 2] for filament 1."""
    return FullSpectrumConfig(
        layer_height_mm=layer_height,
        target_format=target_format,
        color_mappings=[
            ColorMapping(
                input_filament=1,
                output_palette=CyclicPalette(pattern=[1, 2]),
            )
        ],
    )
