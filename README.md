# Full Spectrum 3MF

Slicer-agnostic CLI for **Full Spectrum 3D printing** — Z-layer color dithering that pre-processes 3MF files with per-triangle filament slot assignments, enabling optical color blending across OrcaSlicer, BambuStudio, and PrusaSlicer.

The Full Spectrum technique alternates filament colors at very low layer heights (0.08–0.12 mm) to create optical color blending — producing 10+ perceived colors from just 3–4 loaded filaments.

## Installation

```bash
pip install -e ".[dev]"
```

## Quick Start

### Basic: Alternating two filaments

```bash
full-spectrum model.stl --layer-height 0.1
```

Applies a default cyclic `[1, 2]` pattern — alternating between filament slots 1 and 2 at the specified layer height.

### With palette configuration

```bash
full-spectrum model.stl --config palette.json --output painted.3mf
```

### Gradient blend

```bash
full-spectrum model.stl --config docs/examples/gradient_smooth.json -o gradient.3mf
```

### Target a specific slicer

```bash
full-spectrum model.stl -l 0.08 --format prusaslicer -o model_ps.3mf
full-spectrum model.stl -l 0.08 --format bambu -o model_bambu.3mf
```

### Dry run (validate without writing)

```bash
full-spectrum model.stl -l 0.1 --dry-run -v
```

## CLI Options

| Option | Description |
|--------|-------------|
| `INPUT_FILE` | Path to STL or 3MF file (required) |
| `-l, --layer-height FLOAT` | Layer height in mm (0.04–0.2). Required unless in config. |
| `-c, --config PATH` | Path to JSON palette configuration file |
| `-o, --output PATH` | Output 3MF path. Default: `<input>_painted.3mf` |
| `--format {prusaslicer\|bambu\|both}` | Attribute format. Default: `both` |
| `--flatten` | Flatten sub-painted triangles to dominant filament |
| `-v, --verbose` | Enable debug logging |
| `-q, --quiet` | Suppress all non-error output |
| `--dry-run` | Validate without writing output |
| `--version` | Print version and exit |

## Configuration

Palette configurations are JSON files. See [docs/PALETTE_SCHEMA.md](docs/PALETTE_SCHEMA.md) for full schema documentation.

### Cyclic palette (repeating pattern)

```json
{
  "layer_height_mm": 0.1,
  "target_format": "both",
  "color_mappings": [
    {
      "input_filament": 1,
      "output_palette": {
        "type": "cyclic",
        "pattern": [1, 2]
      }
    }
  ]
}
```

### Gradient palette (smooth transition)

```json
{
  "layer_height_mm": 0.08,
  "target_format": "both",
  "color_mappings": [
    {
      "input_filament": 1,
      "output_palette": {
        "type": "gradient",
        "stops": [[0.0, 1], [1.0, 2]],
        "max_period": 8
      }
    }
  ]
}
```

## Compatibility

| Slicer | Attribute | Status |
|--------|-----------|--------|
| OrcaSlicer 1.7+ | `paint_color` | ✅ Tested |
| BambuStudio 1.2.5+ | `paint_color` | ✅ Tested |
| PrusaSlicer 2.7.3+ | `slic3rpe:mmu_segmentation` | ✅ Tested |

## How It Works

1. Load mesh geometry (STL or 3MF) and parse any existing color assignments
2. Cluster faces by input filament slot
3. For each region: compute Z-layer indices from face centroids
4. Apply dithering pattern (cyclic or gradient) per region
5. Write output 3MF with per-triangle filament attributes

The output 3MF assigns **filament slots** (entries in the slicer's filament list), not physical extruders. The slicer handles mapping filament slots to hardware.

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest -v

# Run with coverage
pytest --cov=full_spectrum --cov-report=term-missing

# Run CLI
full-spectrum --help
```

## License

MIT
