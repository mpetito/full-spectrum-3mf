# Palette Configuration Schema

Full Spectrum uses JSON configuration files to define how input filament slots map to dithered output patterns.

## Schema

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

## Fields

### Top-Level

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `layer_height_mm` | float | Yes | — | Layer height in mm. Valid range: 0.04–0.2. Recommended: 0.08–0.12. |
| `target_format` | string | No | `"both"` | Output attribute format: `"prusaslicer"`, `"bambu"`, or `"both"`. |
| `color_mappings` | array | No | `[]` | Array of input→output palette mappings. |

### ColorMapping

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `input_filament` | int | Yes | 1-based filament slot index from the input model (1–10). |
| `output_palette` | object | Yes | The dithering palette to apply to faces of this input filament. |

### CyclicPalette

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Must be `"cyclic"`. |
| `pattern` | int[] | Yes | Repeating sequence of 1-based filament slot indices. |

### GradientPalette

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Must be `"gradient"`. |
| `stops` | array | Yes | Array of `[t, filament]` pairs. `t` ∈ [0.0, 1.0], sorted ascending. At least 2 stops required. |
| `max_period` | int | No | Maximum dither period. Default: 8. Higher values produce finer gradients but more filament changes. |

## Validation Rules

- `layer_height_mm` must be in [0.04, 0.2]. Warning if outside [0.08, 0.12].
- All filament indices must be in [1, 10].
- Gradient stops must be sorted by `t` in ascending order.
- Gradient stop `t` values must be in [0.0, 1.0].
- At least 2 gradient stops are required.

## Examples

### Binary alternating (purple from red + blue)

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

Filament 1 = red, filament 2 = blue → alternating layers produce perceived purple.

### Smooth gradient (red → yellow)

```json
{
  "layer_height_mm": 0.08,
  "target_format": "both",
  "color_mappings": [
    {
      "input_filament": 1,
      "output_palette": {
        "type": "gradient",
        "stops": [[0.0, 1], [1.0, 3]],
        "max_period": 8
      }
    }
  ]
}
```

Bottom is 100% filament 1 (red), smoothly transitioning to 100% filament 3 (yellow) at top.

### Multi-region: different palettes per input color

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
    },
    {
      "input_filament": 2,
      "output_palette": {
        "type": "gradient",
        "stops": [[0.0, 3], [0.5, 4], [1.0, 5]],
        "max_period": 6
      }
    }
  ]
}
```
