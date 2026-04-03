# Spec: Full Spectrum 3MF — Slicer-Agnostic Layer Stratification CLI

**Date**: 2026-04-03 | **Status**: Draft

## Context

The Full Spectrum technique exploits the visual phenomenon where FDM printers alternating filament colors at very low layer heights (0.08–0.12 mm) produce perceived color blends through optical integration — analogous to CRT phosphor blending or ink halftoning. This creates a vastly expanded perceived color gamut (10+ colors) from just 3–4 loaded filaments.

The existing community tool, `ratdoux/OrcaSlicer-FullSpectrum`, is a monolithic fork of Snapmaker OrcaSlicer tightly coupled to that printer's slicer ecosystem. It requires working within OrcaSlicer's UI and cannot be applied to models already sliced or prepared for other slicers (PrusaSlicer, BambuStudio, Cura, etc.).

This project creates a **slicer-agnostic CLI** that pre-processes a 3D model's per-triangle color assignments directly in the 3MF file before importing into any slicer. By encoding layer-based dither patterns as per-triangle filament slot assignments in the 3MF format (using `slic3rpe:mmu_segmentation` and `paint_color` attributes), the tool enables the Full Spectrum technique across multiple slicers and workflows, unlocking high-quality multi-color printing on tool-changer (Snapmaker U1, Flashforge Creator 5) and AMS-equipped printers (Bambu Lab X1).

> **Filament slots vs. extruders**: The 3MF per-triangle attributes (`mmu_segmentation`, `paint_color`) reference **filament slots** — entries in the slicer's filament list — not physical extruders. The slicer is responsible for mapping filament slots to hardware: on a Bambu X1, all filaments route through a single extruder via AMS; on a Snapmaker H2C, two extruders swap nozzles; on a U1, four extruders each hold one filament. This tool assigns filament slots only; physical routing is the slicer's concern.

## Objective

Build a command-line tool that accepts a 3D model (STL or 3MF) and a palette configuration, computes Z-layer-based color dithering patterns, and outputs a pre-painted 3MF file with per-triangle filament slot assignments compatible with OrcaSlicer, BambuStudio, and PrusaSlicer 2.7.3+ — enabling high-quality Full Spectrum multi-color printing without requiring specialized slicer forks.

## Scope

### In Scope

**MVP Feature Set**:

1. **Input Processing**: Accept STL (binary/ASCII) and 3MF files; parse per-triangle filament slot assignments from both `slic3rpe:mmu_segmentation` (PrusaSlicer) and `paint_color` (BambuStudio/OrcaSlicer) attributes
2. **Geometry Analysis**: Compute face centroids and assign each face to a Z-layer via centroid-based stratification; handle multi-color input by clustering faces per input filament and computing Z ranges independently per region
3. **Palette Algorithms**: Support cyclic (repeating filament sequence) and gradient (frequency-modulated smooth color transitions) palette patterns; implement minority-color anchoring for gradient blends; enforce maximum period clamping (default 8)
4. **Output Serialization**: Generate valid 3MF ZIP with per-triangle filament slot assignments; write both `slic3rpe:mmu_segmentation` and `paint_color` attributes by default (selectable via `--format`)
5. **Configuration**: JSON-based palette config file specifying layer height, palette type, color mappings, and gradient stops
6. **CLI Interface**: Standard command-line tool with `--layer-height`, `--config`, `--output`, `--format`, `--flatten`, `--verbose`, `--dry-run`, `--version`, `--help` flags
7. **Compatibility**: Support OrcaSlicer, BambuStudio, and PrusaSlicer 2.7.3+; handle models with 100k+ triangles efficiently (O(n) centroid assignment)

### Out of Scope

1. **Slicer Integration**: No built-in slicer plugins or direct slicer bindings; the tool outputs a file that enters an existing slicer workflow
2. **Interactive UI**: No GUI; CLI-only interface
3. **Sub-Triangle Precision**: No sub-triangle recursive bisection encoding; whole-triangle coloring only
4. **Advanced Mesh Subdivision**: Mesh slicing at Z-plane boundaries (Strategy C) deferred to v1.1; MVP uses centroid-based assignment (Strategy A)
5. **Multiple Objects per 3MF**: Single object per 3MF in MVP; complex multi-object assemblies deferred
6. **Real-Time Preview**: No interactive 3D preview of painted mesh; `--dry-run` validates without writing
7. **Visual Color Simulation**: No RGB color conversion or blending simulation; the tool assigns filament slot indices only

## Requirements

### Functional

#### Input Handling

- Accept STL files in binary or ASCII format and 3MF files as input
- Parse per-triangle filament slot assignments from 3MF `slic3rpe:mmu_segmentation` attribute (PrusaSlicer namespace)
- Parse per-triangle filament slot assignments from 3MF `paint_color` attribute (BambuStudio/OrcaSlicer namespace)
- Decode bit-packed hexadecimal filament encoding (`"4"` → filament 1, `"8"` → filament 2, `"0C"` → filament 3, etc.)
- Infer default filament for uncolored triangles from `Metadata/Slic3r_PE_model.config` metadata; default to filament 1 if absent
- For STL input with no color data, treat entire model as single-color input (filament 1)
- Detect sub-triangle painted regions (multi-byte hex strings in `mmu_segmentation`); reject with clear error message or flatten to dominant filament via `--flatten` flag

#### Geometry Processing

- Load mesh geometry using **trimesh** library; support STL, 3MF, OBJ formats
- Compute per-face centroid Z-coordinates via `mesh.triangles_center[:, 2]` (numpy vectorized operations)
- Assign each face to a layer via `floor((z_centroid - z_min + ε) / layer_height)` with floating-point tolerance (ε = 1% of layer_height)
- For multi-color input: cluster faces by input filament; compute per-region Z ranges independently (min/max face centroids within each region); apply layer assignment within each region's local Z extent
- Handle disconnected islands of same input color as independent gradient domains (connected-component analysis on face adjacency)

#### Palette Configuration

- JSON configuration file with required schema: `layer_height_mm`, `target_format`, `color_mappings` array
- Cyclic palette type: repeating sequence of 1-based filament slot indices (e.g., `[1, 2]` for binary red-blue dither)
- Gradient palette type: multi-stop transitions with filament anchors at normalized Z positions; support stops array as `[[t, filament], ...]` where t ∈ [0.0, 1.0]
- Gradient minority-color anchoring: minority color occupies exactly 1 layer per period; majority color count scales inversely with blend ratio
- Maximum period enforcement (default 8): clamp computed period to prevent excessive pattern complexity; allow user override via `max_period` config field
- Configuration validation: reject out-of-range filament indices (must be 1–10); validate JSON syntax; confirm required fields present; warn on unused filament references
- Default palette fallback: if no config provided or `color_mappings` empty, apply cyclic `[1, 2]` to entire model

#### Dithering Algorithms

- **Cyclic (Modulus) Palette**: for each layer iₗ, filament = `pattern[iₗ mod len(pattern)]`
- **Gradient (Frequency-Modulated) Palette**:
  - Normalize layer position within region to t ∈ [0.0, 1.0]
  - Interpolate between gradient stops to find two adjacent filaments and local_t
  - Compute blend ratio R from local_t
  - Build repeating pattern with minority color anchored to 1 layer: `period = clamped_round(1.0 / min(R, 1-R))`
  - Pattern layout: minority color at position 0, majority fills remainder
  - Apply pattern cyclically: `filament = pattern[iₗ mod len(pattern)]`
- Both algorithms handle edge cases: R → 0 or 1 returns mono-color; default clamping prevents period overflow

#### Output Serialization

- Generate valid 3MF ZIP archive with correct directory structure and MIME types
- Write per-triangle filament as `slic3rpe:mmu_segmentation` attribute (PrusaSlicer format) with namespace declaration on root element
- Write per-triangle filament as `paint_color` attribute (BambuStudio/OrcaSlicer format)
- Support `--format prusaslicer|bambu|both` flag: "prusaslicer" writes only `slic3rpe:mmu_segmentation`, "bambu" writes only `paint_color`, "both" (default) writes both
- Encode 1-based filament index to hexadecimal via lookup table: 1→`"4"`, 2→`"8"`, ..., 10→`"7C"` (low 2 bits always 00 for whole-triangle coloring)
- Include boilerplate files with correct content:
  - `[Content_Types].xml`: XML declarations for .rels and model files
  - `_rels/.rels`: relationship manifest pointing to 3D/3dmodel.model
  - `3D/3dmodel.model`: XML model with namespaces, vertices, triangles, and per-triangle attributes
  - `Metadata/Slic3r_PE_model.config`: default filament for object
- Ensure ZIP uses forward slashes in entry names; compression via ZIP_DEFLATED
- Validate output 3MF can be unpacked and parsed by XML validator before returning success

#### CLI Interface

- Single main command accepting positional input file path
- Flags:
  - `--layer-height FLOAT` (required unless in config): layer height in mm (0.04–0.2 mm range)
  - `--config PATH` (optional): path to JSON palette config file
  - `--output PATH` (optional, default: `input_name_painted.3mf`): output file path
  - `--format {prusaslicer|bambu|both}` (optional, default: `both`): attribute format to write
  - `--flatten` (flag): flatten sub-painted triangles to dominant filament instead of rejecting
  - `--verbose` (flag): enable debug logging (per-face assignments, layer statistics)
  - `--quiet` (flag): suppress all non-error output
  - `--dry-run` (flag): validate without writing output file
  - `--version`: print tool version
  - `--help`: print usage information
- Exit codes: 0 on success; non-zero (1, 2, 3, etc.) for distinct error categories (invalid input, config error, write failure)
- Error messages: clear, actionable, include file path and line number where applicable

### Non-Functional

#### Performance

- Process meshes with 100k+ triangles in <10 seconds on standard hardware
- Memory usage scales linearly with face count (O(n)); no quadratic algorithms
- Centroid computation vectorized via numpy; no explicit Python loops over face arrays

#### Compatibility

- **Python**: 3.10+ (modern type hints, match statements supported)
- **Platform**: Windows, macOS, Linux
- **Output Compatibility**: 3MF output valid per 3MF Core Specification; compatible with OrcaSlicer 1.7.x+, BambuStudio 1.2.5+, PrusaSlicer 2.7.3+
- **Input Compatibility**: Accept STL (binary/ASCII); accept 3MF per Core Specification with optional PrusaSlicer and BambuStudio namespace extensions

#### Error Handling

- File I/O errors: distinguish read errors (missing input), write errors (disk full), and parse errors (corrupt ZIP or XML)
- Validation errors: report which field failed validation (e.g., "Filament 15 out of range at color_mappings[2]")
- Warnings: log when largest layer gap detected, when default palette used, when sub-painted regions flattened

#### Testing

- Unit tests for:
  - Filament encoding/decoding (hex string ↔ integer)
  - Gradient algorithm (ratio → pattern generation)
  - Layer assignment (centroid Z → layer index)
  - Config parsing (valid/invalid JSON schemas)
  - Face clustering by input filament
- Integration tests for:
  - Round-trip: STL → painted 3MF → unpacked XML validation
  - Multi-color input: 3MF with pre-existing colors → output respects input regions
  - Gradient smoothness: verify no period jumps across stops
- Compatibility tests: output files import into OrcaSlicer, BambuStudio, PrusaSlicer without errors

#### Documentation

- README: quick-start guide with example commands
- CLI help text: full flag descriptions and examples
- Config schema documentation with example configs
- Design rationale in code comments for algorithm choices

## Design Constraints

- **Hexadecimal Encoding**: per-triangle filament indices encoded as bit-packed hex; low 2 bits always 00 for whole-triangle coloring; no custom encoding
- **Namespace Differences**: PrusaSlicer uses XML namespace `http://schemas.slic3r.org/3mf/2017/06` with `slic3rpe:mmu_segmentation` attribute; BambuStudio/OrcaSlicer use `paint_color` in default namespace; both must be readable and writable
- **Layer Height Range**: recommended sweet spot 0.08–0.12 mm; support range 0.04–0.2 mm; warn if outside typical range
- **Single Object per 3MF**: only one `<object type="model">` per file in MVP; multi-object assemblies rejected with clear error
- **No Sub-Triangle Coloring**: whole-triangle assignment only; sub-painted regions (recursive bisection trees in `mmu_segmentation`) either rejected or flattened
- **Z-Axis Alignment Only**: dithering is inherently horizontal layer-based; sloped surfaces naturally blend different layer colors depending on viewing angle
- **Centroid-Based Assignment (MVP)**: faces assigned to layer containing their centroid; faces spanning layer boundaries assigned to whichever layer their geometric center falls in

## Acceptance Criteria

- [ ] CLI successfully processes binary STL (e.g., cube.stl → cube_painted.3mf) with no errors
- [ ] CLI successfully processes STL with `--config palette.json` containing cyclic pattern and outputs valid 3MF
- [ ] CLI successfully processes 3MF with pre-existing `slic3rpe:mmu_segmentation` colors, re-processes, and preserves object structure
- [ ] Gradient palette correctly computes intermediate blend ratios; verify pattern does not jump between stops
- [ ] Output 3MF unpacks correctly; `3D/3dmodel.model` parses as valid XML; all triangle attributes present and valid hex
- [ ] `--format prusaslicer` outputs only `slic3rpe:mmu_segmentation`; `--format bambu` outputs only `paint_color`; `--format both` outputs both
- [ ] `--dry-run` validates input and config but does not create output file
- [ ] Error handling: rejecting out-of-range filament (11) in config returns non-zero exit code with clear message
- [ ] Error handling: missing `--layer-height` with no config file returns non-zero exit code and prompts user
- [ ] `--flatten` flag successfully converts sub-painted triangles to dominant filament and completes processing
- [ ] Large mesh (100k triangles): completes in <10 seconds on standard hardware
- [ ] Output 3MF imports into OrcaSlicer, BambuStudio, and PrusaSlicer without errors (manual verification)
- [ ] Multi-region input (3MF with red and blue faces): each region receives independent gradient mapping as per config
- [ ] Default palette invoked when config absent: model colored with cyclic [1, 2] pattern globally

## Decisions

| Decision                        | Choice                                     | Rationale                                                                       |
| ------------------------------- | ------------------------------------------ | ------------------------------------------------------------------------------- |
| Internal filament indexing      | 1-based                                    | Matches slicer filament list UIs; avoids off-by-one confusion for users         |
| Layer assignment strategy (MVP) | Centroid-based (Strategy A)                | O(n), sufficient for tessellated meshes; subdivision deferred to v1.1           |
| Config format                   | JSON                                       | Human-readable, stdlib support, lower learning curve than YAML/TOML             |
| CLI framework                   | click                                      | Ergonomic, flexible argument parsing, built-in help formatting                  |
| Output attribute format         | Both `slic3rpe` + `paint_color` by default | Maximizes cross-slicer compatibility; specializable via `--format`              |
| Sub-painted triangle handling   | Reject by default; opt-in `--flatten`      | Prevents accidental precision loss; user consciously chooses simplification     |
| Disconnected same-color regions | Independent gradient domains               | Smooth per-region gradients; prevents unintended pattern repetition across gaps |
| Max period default              | 8 layers                                   | Balances dither quality with pattern stability; community standard              |

## Open Questions

None — the design document is comprehensive. Edge cases (degenerate meshes, zero-area triangles) are covered by validation constraints and floating-point tolerance.
