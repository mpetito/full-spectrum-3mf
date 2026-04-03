# Plan: Full Spectrum 3MF — Slicer-Agnostic Layer Stratification CLI

**Spec**: [specs/001-full-spectrum-3mf/spec.md](specs/001-full-spectrum-3mf/spec.md) | **Design**: [docs/full-spectrum.md](docs/full-spectrum.md) | **Date**: 2026-04-03

## Summary

Full Spectrum is a slicer-agnostic CLI that preprocesses 3D models by assigning per-triangle filament colors via Z-layer dithering, enabling optical color blending through rapid filament switching. This plan covers building a complete MVP that accepts STL or 3MF input with optional color data, applies cyclic or gradient dithering patterns via JSON configuration, and outputs a valid 3MF file compatible with OrcaSlicer, BambuStudio, and PrusaSlicer 2.7.3+. The implementation uses `src/full_spectrum/` package structure with trimesh, numpy, click, and lxml, achieves O(n) centroid-based layer assignment, and enforces <10s processing for 100k+ triangle meshes.

## Architecture Decisions

| Decision              | Choice                                                         | Rationale                                                                                       |
| --------------------- | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Package layout        | `src/full_spectrum/` (PEP 517 / modern Python)                 | Industry standard; enables editable installs; clear separation from tests and docs              |
| Config validation     | Python dataclasses (stdlib)                                    | Lightweight; avoid Pydantic dependency for MVP                                                  |
| Mesh loading          | `trimesh` 4.0+                                                 | Pure Python; vectorized numpy operations; `mesh.triangles_center` gives face centroids directly |
| XML parsing           | `lxml` (pip)                                                   | Namespace-aware round-tripping; required for preserving xmlns:slic3rpe declarations             |
| CLI framework         | `click` (pip)                                                  | Ergonomic argument parsing; automatic `--help`; built-in error handling                         |
| Filament indexing     | 1-based (users see "filament 1–10")                            | Matches slicer filament list UIs; avoids off-by-one errors                                      |
| Layer assignment      | Centroid-based (Strategy A)                                    | O(n) complexity; sufficient for tessellated meshes; sub-face precision deferred to v1.1         |
| Output format default | Write both `slic3rpe:mmu_segmentation` + `paint_color`         | Maximizes cross-slicer compatibility; selectable via `--format` flag                            |
| Sub-painted triangles | Reject by default; opt-in `--flatten`                          | Preserves data integrity; requires conscious user approval for simplification                   |
| Max period default    | 8 layers                                                       | Community standard; prevents excessive pattern complexity; overridable in config                |
| Python version        | 3.10+                                                          | Modern type hints, match statements, walrus operators                                           |
| Testing               | `pytest` with `tests/` directory                               | Standard; fixtures in `tests/fixtures/`; separate test packages per module                      |
| Entry point           | `full-spectrum` command via `pyproject.toml [project.scripts]` | User-friendly CLI invocation; standard Python package convention                                |

## Implementation Phases

### Phase 1: Project Bootstrap

**Objective**: Initialize repository structure, package metadata, development tooling.

1. [ ] Create `pyproject.toml` with:
   - Package name `full-spectrum`, version `0.1.0`, `requires-python = ">=3.10"`
   - Dependencies: `trimesh>=4.0`, `numpy>=1.24`, `click>=8.0`, `lxml>=4.9`
   - Dev dependencies: `pytest>=7.0`, `pytest-cov>=4.0`
   - Entry point: `[project.scripts]` → `full-spectrum = "full_spectrum.cli:main"`
   - Build system: setuptools with `src/` layout
2. [ ] Create directory structure: `src/full_spectrum/`, `tests/unit/`, `tests/integration/`, `tests/acceptance/`, `tests/fixtures/`
3. [ ] Create `src/full_spectrum/__init__.py` with `__version__ = "0.1.0"` and package docstring
4. [ ] Create `src/full_spectrum/__main__.py` delegating to `cli.main()`
5. [ ] Create stub modules: `cli.py`, `encoding.py`, `config.py`, `mesh.py`, `palette.py`, `threemf.py`, `pipeline.py`
6. [ ] Create `.gitignore` (Python standard), `README.md` (placeholder), `tests/conftest.py`
7. [ ] Verification: `pip install -e ".[dev]"` succeeds; `full-spectrum --help` runs; `pytest --co` discovers tests

---

### Phase 2: Core Data Layer — Filament Encoding & Config

**Objective**: Implement filament hex encode/decode functions, JSON configuration schema via dataclasses, validation logic.

#### `src/full_spectrum/encoding.py`

1. [ ] Implement `FILAMENT_HEX_TABLE: dict[int, str]` — lookup table mapping 1→`"4"`, 2→`"8"`, 3→`"0C"`, 4→`"1C"`, 5→`"2C"`, 6→`"3C"`, 7→`"4C"`, 8→`"5C"`, 9→`"6C"`, 10→`"7C"`
2. [ ] Implement `HEX_FILAMENT_TABLE: dict[str, int]` — reverse lookup (uppercase-normalized)
3. [ ] Implement `hex_to_filament(hex_str: str) -> int`:
   - Map known hex codes to 1-based filament via table
   - Reject strings > 2 hex chars → `ValueError("Sub-painted triangle detected")`
   - Reject unknown codes → `ValueError("Invalid filament hex code: {hex_str}")`
4. [ ] Implement `filament_to_hex(filament: int) -> str`:
   - Map 1-based filament to hex via table
   - Reject filament < 1 or > 10 → `ValueError`
5. [ ] Implement `is_sub_painted(hex_str: str) -> bool` — True if len > 2 chars

#### `src/full_spectrum/config.py`

6. [ ] Define dataclasses:
   - `CyclicPalette(pattern: list[int])` — list of 1-based filament indices
   - `GradientStop(t: float, filament: int)` — t ∈ [0.0, 1.0]
   - `GradientPalette(stops: list[GradientStop], max_period: int = 8)`
   - `ColorMapping(input_filament: int, output_palette: CyclicPalette | GradientPalette)`
   - `FullSpectrumConfig(layer_height_mm: float, target_format: str, color_mappings: list[ColorMapping])`
7. [ ] Implement `load_config(path: str) -> FullSpectrumConfig`:
   - `json.load()` → dict → dataclass tree; wrap parse errors with file path context
   - Dispatch on `output_palette.type` field: `"cyclic"` → `CyclicPalette`, `"gradient"` → `GradientPalette`
8. [ ] Implement `validate_config(config: FullSpectrumConfig) -> list[str]`:
   - Return list of warning strings (empty = valid)
   - Error (raise `ConfigError`): filament indices outside [1, 10]
   - Error: gradient stops not sorted by t
   - Error: gradient stops t outside [0.0, 1.0]
   - Error: layer_height_mm outside [0.04, 0.2]
   - Warning: layer_height_mm outside [0.08, 0.12] sweet spot
   - Warning: target_format not in `{"prusaslicer", "bambu", "both"}`
9. [ ] Define `ConfigError(Exception)` with descriptive message
10. [ ] Implement `default_config(layer_height: float, target_format: str = "both") -> FullSpectrumConfig`:
    - Returns config with single cyclic `[1, 2]` mapping for input_filament 1
11. [ ] Create test fixtures: `tests/fixtures/valid_palette.json`, `tests/fixtures/invalid_palette.json`, `tests/fixtures/default_palette.json`

#### Tests

12. [ ] `tests/unit/test_encoding.py`:
    - `test_hex_to_filament_valid_all_values()` — parametrize all 10 codes
    - `test_hex_to_filament_case_insensitive()` — `"0c"` and `"0C"` both → 3
    - `test_hex_to_filament_sub_painted_rejection()` — long string raises ValueError
    - `test_filament_to_hex_roundtrip()` — encode(decode(x)) == x for all
    - `test_filament_to_hex_out_of_range()` — 0 and 11 raise ValueError
    - `test_is_sub_painted()`
13. [ ] `tests/unit/test_config.py`:
    - `test_load_config_valid()`, `test_load_config_invalid_json()`, `test_validate_filament_range()`, `test_validate_gradient_stops_sorted()`, `test_validate_gradient_bounds()`, `test_default_config()`
14. [ ] Verification: `pytest tests/unit/test_encoding.py tests/unit/test_config.py -v` — 100% pass

---

### Phase 3: 3MF I/O — Reading and Writing

**Objective**: Implement 3MF ZIP unpacking, XML parsing for triangle attributes, and serialization.

#### `src/full_spectrum/threemf.py`

1. [ ] Define constants:
   - `NAMESPACES` dict: `{"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02", "slic3rpe": "http://schemas.slic3r.org/3mf/2017/06"}`
   - `CONTENT_TYPES_XML` string, `RELS_XML` string, `CONFIG_XML_TEMPLATE` string
2. [ ] Implement `read_3mf(path: str, flatten: bool = False) -> ThreeMFData`:
   - `ThreeMFData = dataclass(vertices: np.ndarray, faces: np.ndarray, face_colors: dict[int, int], default_filament: int)`
   - Unpack ZIP via `zipfile.ZipFile`; read `3D/3dmodel.model`
   - Parse XML via `lxml.etree`; extract vertices, faces from `<mesh>` element
   - Extract per-triangle colors: check `slic3rpe:mmu_segmentation`, then `paint_color`
   - If sub-painted detected and `flatten=False` → raise `ThreeMFError`
   - If sub-painted detected and `flatten=True` → call `hex_to_filament` with first 2 chars (dominant)
   - Validate single `<object type="model">` element; reject multi-object
3. [ ] Implement `parse_default_filament(zip_file: ZipFile) -> int`:
   - Read `Metadata/Slic3r_PE_model.config` if present; parse XML for `key="extruder"` (slicer's internal naming)
   - Return 1 if absent
4. [ ] Implement `write_3mf(output_path: str, vertices: np.ndarray, faces: np.ndarray, face_filaments: np.ndarray, default_filament: int = 1, target_format: str = "both") -> None`:
   - Build `3D/3dmodel.model` XML via `lxml.etree`:
     - Root `<model>` with correct namespace declarations
     - `<vertices>` and `<triangles>` elements
     - Per-triangle: if filament != default, write `slic3rpe:mmu_segmentation` and/or `paint_color` per format
   - Build boilerplate: `[Content_Types].xml`, `_rels/.rels`, `Metadata/Slic3r_PE_model.config`
   - Pack into ZIP with forward slashes; `ZIP_DEFLATED` compression
   - Validate output: re-read and parse XML to confirm well-formed
5. [ ] Define `ThreeMFError(Exception)`

#### Tests

6. [ ] `tests/unit/test_threemf.py`:
   - `test_read_3mf_valid()`, `test_read_3mf_invalid_zip()`, `test_single_object_enforcement()`
   - `test_parse_colors_slic3rpe()`, `test_parse_colors_paint_color()`, `test_parse_colors_mixed()`
   - `test_sub_painted_detection()`, `test_sub_painted_flatten()`
   - `test_write_3mf_prusaslicer()`, `test_write_3mf_bambu()`, `test_write_3mf_both()`
   - `test_write_3mf_valid_zip()`, `test_write_3mf_namespace_declaration()`
7. [ ] Create test fixtures: `tests/fixtures/painted.3mf`, `tests/fixtures/painted_bambu.3mf`, `tests/fixtures/sub_painted.3mf`
8. [ ] Verification: `pytest tests/unit/test_threemf.py -v` — 100% pass

---

### Phase 4: Geometry Processing — Mesh Loading & Layer Assignment

**Objective**: Load mesh geometry via trimesh, compute centroids, assign faces to Z-layers, handle multi-region clustering.

#### `src/full_spectrum/mesh.py`

1. [ ] Implement `load_mesh(path: str) -> trimesh.Trimesh`:
   - Uses `trimesh.load(path)` for STL, 3MF, OBJ
   - Validates non-empty mesh with triangles
   - Raises `MeshError` on degenerate/invalid input
2. [ ] Implement `compute_face_layers(mesh: trimesh.Trimesh, layer_height: float) -> np.ndarray`:
   - `centroids_z = mesh.triangles_center[:, 2]` (vectorized)
   - `z_min = centroids_z.min()`, epsilon = `layer_height * 0.01`
   - `layer_indices = np.floor((centroids_z - z_min + epsilon) / layer_height).astype(int)`
   - Returns shape `(n_faces,)` int array
3. [ ] Implement `compute_region_layers(mesh: trimesh.Trimesh, layer_height: float, face_indices: np.ndarray) -> tuple[np.ndarray, int]`:
   - Compute layers for a subset of faces relative to that region's z_min
   - Returns `(layer_indices_within_region, total_layers_in_region)`
4. [ ] Implement `cluster_faces_by_filament(face_colors: dict[int, int], n_faces: int) -> dict[int, np.ndarray]`:
   - Groups face indices by input filament
   - Returns `{filament: np.ndarray([face_idx, ...])}`
5. [ ] Define `MeshError(Exception)`

#### Tests

6. [ ] `tests/unit/test_mesh.py`:
   - `test_load_mesh_stl()`, `test_load_mesh_invalid()`
   - `test_compute_face_layers_single_region()` — cube with known dimensions
   - `test_compute_face_layers_epsilon_tolerance()` — faces exactly at boundary
   - `test_compute_region_layers()` — subset region Z range
   - `test_cluster_faces_single_color()`, `test_cluster_faces_multi_color()`
7. [ ] Create test fixture: `tests/fixtures/cube.stl` (programmatically generated in conftest.py via trimesh)
8. [ ] Verification: `pytest tests/unit/test_mesh.py -v` — 100% pass

---

### Phase 5: Dithering Algorithms — Cyclic & Gradient

**Objective**: Implement cyclic palette and gradient algorithms with minority-color anchoring.

#### `src/full_spectrum/palette.py`

1. [ ] Implement `apply_cyclic(layer_indices: np.ndarray, pattern: list[int]) -> np.ndarray`:
   - Vectorized: `np.array(pattern)[layer_indices % len(pattern)]`
   - Returns shape `(n_faces,)` of 1-based filament ints
2. [ ] Implement `compute_gradient_pattern(ratio: float, color_a: int, color_b: int, max_period: int = 8) -> list[int]`:
   - R → 0: return `[color_a]`
   - R → 1: return `[color_b]`
   - R ≤ 0.5: minority=color_b, majority=color_a; period = `min(round(1.0 / R), max_period)`
   - R > 0.5: minority=color_a, majority=color_b; period = `min(round(1.0 / (1.0 - R)), max_period)`
   - Pattern: `[minority] + [majority] * (period - 1)`
3. [ ] Implement `apply_gradient(layer_indices: np.ndarray, total_layers: int, stops: list[tuple[float, int]], max_period: int = 8) -> np.ndarray`:
   - Normalize: `t = layer_indices / max(total_layers - 1, 1)`
   - For each face: find enclosing stop pair, compute local_t, get pattern, index cyclically
   - Returns shape `(n_faces,)` of 1-based filament ints
4. [ ] Define `PaletteError(Exception)`

#### Tests

5. [ ] `tests/unit/test_palette.py`:
   - `test_cyclic_single()`, `test_cyclic_alternating()`, `test_cyclic_triple()`
   - `test_gradient_ratio_zero()`, `test_gradient_ratio_one()`, `test_gradient_ratio_half()`
   - `test_gradient_ratio_quarter()` — R=0.25: [B, A, A, A]
   - `test_gradient_ratio_third()` — R=0.33: [B, A, A]
   - `test_gradient_period_clamp()` — max_period enforced
   - `test_apply_gradient_single_stop_pair()`, `test_apply_gradient_multi_stop()`
   - `test_apply_gradient_boundary_values()`
6. [ ] Verification: `pytest tests/unit/test_palette.py -v` — 100% pass

---

### Phase 6: Pipeline Orchestration

**Objective**: Wire all modules together into a cohesive processing flow.

#### `src/full_spectrum/pipeline.py`

1. [ ] Implement `process(input_path: str, config: FullSpectrumConfig, output_path: str, flatten: bool = False, dry_run: bool = False) -> PipelineResult`:
   - `PipelineResult = dataclass(success: bool, face_count: int, layer_count: int, filament_distribution: dict[int, int], warnings: list[str])`
   - Steps:
     1. Detect input type (STL vs 3MF) by extension
     2. Load mesh via `load_mesh()`
     3. If 3MF: read face colors via `read_3mf()` (with flatten flag); else: empty face_colors
     4. Cluster faces by input filament via `cluster_faces_by_filament()`
     5. For each input filament region:
        a. Look up `ColorMapping` in config (fall back to default cyclic [1,2] if unmapped)
        b. Compute region layers via `compute_region_layers()`
        c. Apply palette (cyclic or gradient) to get output filaments
     6. Assemble final `face_filaments` array (shape: n_faces)
     7. If not dry_run: write 3MF via `write_3mf()` with config.target_format
     8. Return `PipelineResult` with statistics

#### Tests

2. [ ] `tests/integration/test_pipeline.py`:
   - `test_pipeline_stl_cyclic()` — STL + cyclic → valid 3MF
   - `test_pipeline_3mf_gradient()` — painted 3MF + gradient → remapped 3MF
   - `test_pipeline_multi_region()` — independent per-region palettes
   - `test_pipeline_sub_painted_rejection()` — error without --flatten
   - `test_pipeline_sub_painted_flatten()` — succeed with --flatten
   - `test_pipeline_dry_run()` — no output file created
   - `test_pipeline_default_palette()` — no config → cyclic [1,2]
   - `test_pipeline_statistics()` — PipelineResult fields accurate
3. [ ] `tests/integration/test_roundtrip.py`:
   - `test_roundtrip_stl()` — process cube.stl, unpack output, verify attributes in XML
   - `test_roundtrip_3mf()` — load painted.3mf, re-process, verify colors remapped
   - `test_roundtrip_gradient_smoothness()` — verify no period jumps across stops
   - `test_roundtrip_xml_validity()` — output always well-formed XML
4. [ ] Verification: `pytest tests/integration/ -v` — 100% pass

---

### Phase 7: CLI Interface

**Objective**: Implement click-based CLI with all flags, argument parsing, error handling, exit codes.

#### `src/full_spectrum/cli.py`

1. [ ] Implement `main()` click command with decorators:
   - `@click.command()`, `@click.argument('input_file', type=click.Path(exists=True))`
   - Options: `--layer-height/-l`, `--config/-c`, `--output/-o`, `--format`, `--flatten`, `--verbose/-v`, `--quiet/-q`, `--dry-run`, `--version`
2. [ ] Argument validation:
   - If `config` absent and `layer_height` absent → `click.UsageError("Either --config or --layer-height required")`
   - If both present: config takes precedence; CLI `--layer-height` overrides config's `layer_height_mm`
3. [ ] Default output path: `Path(input_file).stem + "_painted.3mf"`
4. [ ] Load config: `load_config(config_path)` or `default_config(layer_height, format)`
5. [ ] Call `process()` pipeline; handle exceptions by category:
   - `ConfigError` → exit code 2
   - `MeshError` → exit code 1
   - `ThreeMFError` → exit code 1
   - `OSError/IOError` → exit code 3
   - Unexpected → exit code 4
6. [ ] If verbose: print `PipelineResult` statistics
7. [ ] If not quiet: print success message with output path
8. [ ] Implement `print_version()` eager callback

#### Tests

9. [ ] `tests/acceptance/test_cli_acceptance.py` (using `click.testing.CliRunner`):
   - `test_cli_help()`, `test_cli_version()`
   - `test_cli_stl_with_layer_height()` — basic success path
   - `test_cli_stl_with_config()` — config file path
   - `test_cli_output_path()` — custom output
   - `test_cli_format_flags()` — prusaslicer, bambu, both
   - `test_cli_flatten()`, `test_cli_verbose()`, `test_cli_quiet()`, `test_cli_dry_run()`
   - `test_cli_missing_layer_height()` — exit code 2
   - `test_cli_invalid_input()` — exit code 1
   - `test_cli_invalid_config()` — exit code 2
10. [ ] Verification: `pytest tests/acceptance/ -v` — 100% pass; `full-spectrum --help` displays complete help

---

### Phase 8: Testing & Fixtures

**Objective**: Fill remaining test gaps, generate test fixtures programmatically, target ≥85% coverage.

1. [ ] Create `tests/conftest.py` shared fixtures:
   - `simple_cube_stl(tmp_path)` — generate binary STL cube via trimesh and save to tmp
   - `simple_config()` — return minimal `FullSpectrumConfig`
   - `painted_3mf(tmp_path)` — generate 3MF with per-triangle slic3rpe attributes
   - `cli_runner()` — `click.testing.CliRunner` instance
2. [ ] Create programmatic fixture generators (avoid checking in binary files):
   - `tests/fixtures/generate_fixtures.py` — script to create cube.stl, painted.3mf, sub_painted.3mf
   - JSON fixtures: `valid_palette.json`, `invalid_palette.json`, `default_palette.json`
3. [ ] Add performance test: `test_pipeline_large_mesh()` — generate 100k triangle mesh, assert <10s
4. [ ] Run full suite: `pytest --cov=full_spectrum --cov-report=term-missing -v`
5. [ ] Verification: ≥85% coverage; all tests pass; no warnings

---

### Phase 9: Documentation & Examples

**Objective**: Write README, config schema docs, example configs.

1. [ ] Expand `README.md`:
   - Project description (1 paragraph)
   - Installation: `pip install full-spectrum`
   - Quick start: 3 example commands (STL, config, gradient)
   - Configuration section: link to `docs/PALETTE_SCHEMA.md`
   - Compatibility: supported slicers
   - Contributing: dev setup instructions
2. [ ] Create `docs/PALETTE_SCHEMA.md`:
   - JSON schema documentation with required/optional fields
   - Cyclic palette examples
   - Gradient palette examples with stops
   - Validation rules
3. [ ] Create example configs in `docs/examples/`:
   - `simple_cyclic.json` — binary red-blue dither
   - `gradient_smooth.json` — red → yellow gradient
   - `multi_region.json` — independent per-color palettes
   - `high_quality.json` — recommended 0.08mm settings
4. [ ] Verification: README renders correctly; example configs parse without error; `full-spectrum --help` matches docs

---

## File Changes

| File                                      | Action | Purpose                                              |
| ----------------------------------------- | ------ | ---------------------------------------------------- |
| `pyproject.toml`                          | Create | Package metadata, dependencies, entry point          |
| `src/full_spectrum/__init__.py`           | Create | Package root, version constant                       |
| `src/full_spectrum/__main__.py`           | Create | `python -m full_spectrum` entry point                |
| `src/full_spectrum/cli.py`                | Create | Click CLI commands and main()                        |
| `src/full_spectrum/encoding.py`           | Create | Filament hex encode/decode, lookup tables            |
| `src/full_spectrum/config.py`             | Create | Dataclasses, JSON loading, validation                |
| `src/full_spectrum/threemf.py`            | Create | 3MF ZIP read/write, XML parsing/serialization        |
| `src/full_spectrum/mesh.py`               | Create | Mesh loading, centroid computation, layer assignment |
| `src/full_spectrum/palette.py`            | Create | Cyclic & gradient algorithm implementations          |
| `src/full_spectrum/pipeline.py`           | Create | Pipeline orchestration                               |
| `tests/conftest.py`                       | Create | Shared pytest fixtures                               |
| `tests/unit/test_encoding.py`             | Create | Encoding unit tests                                  |
| `tests/unit/test_config.py`               | Create | Config unit tests                                    |
| `tests/unit/test_threemf.py`              | Create | 3MF I/O unit tests                                   |
| `tests/unit/test_mesh.py`                 | Create | Mesh processing unit tests                           |
| `tests/unit/test_palette.py`              | Create | Palette algorithm unit tests                         |
| `tests/integration/test_pipeline.py`      | Create | Pipeline orchestration tests                         |
| `tests/integration/test_roundtrip.py`     | Create | Round-trip validation tests                          |
| `tests/acceptance/test_cli_acceptance.py` | Create | CLI end-to-end tests                                 |
| `tests/fixtures/generate_fixtures.py`     | Create | Programmatic fixture generation                      |
| `tests/fixtures/valid_palette.json`       | Create | Valid config test fixture                            |
| `tests/fixtures/invalid_palette.json`     | Create | Invalid config test fixture                          |
| `tests/fixtures/default_palette.json`     | Create | Minimal config test fixture                          |
| `.gitignore`                              | Create | Python standard ignores                              |
| `README.md`                               | Create | Project overview, quick-start, usage                 |
| `docs/PALETTE_SCHEMA.md`                  | Create | JSON configuration schema docs                       |
| `docs/examples/simple_cyclic.json`        | Create | Example: binary cyclic palette                       |
| `docs/examples/gradient_smooth.json`      | Create | Example: smooth gradient                             |
| `docs/examples/multi_region.json`         | Create | Example: multi-region palettes                       |
| `docs/examples/high_quality.json`         | Create | Example: recommended settings                        |

## Testing Strategy

| Category          | Scope                                                              | Tools                           |
| ----------------- | ------------------------------------------------------------------ | ------------------------------- |
| Unit tests        | Individual functions: encoding, config, palette, mesh, threemf     | pytest, parametrize             |
| Integration tests | Module interactions: pipeline orchestration, round-trip validation | pytest                          |
| Acceptance tests  | Full CLI end-to-end with temporary files                           | pytest, click.testing.CliRunner |
| Performance tests | 100k+ triangle mesh completes in <10s                              | pytest with timing assertions   |
| Fixtures          | Programmatically generated STL/3MF; JSON config files              | trimesh, conftest.py            |

**Execution order**: Unit (Phases 2–5) → Integration (Phase 6) → Acceptance (Phase 7) → Full suite (Phase 8)
**Coverage target**: ≥85% via `pytest-cov`

## Risks & Mitigations

| Risk                                                                  | Likelihood | Mitigation                                                                                   |
| --------------------------------------------------------------------- | ---------- | -------------------------------------------------------------------------------------------- |
| Sub-painted triangle detection complexity (false positives/negatives) | Medium     | Robust check on hex string length > 2 chars; `--flatten` escape hatch                        |
| 3MF XML namespace handling breaks slicer import                       | Medium     | Use lxml for namespace-aware output; always declare xmlns:slic3rpe; test with actual slicers |
| Floating-point layer boundary errors                                  | Medium     | Epsilon tolerance = 1% of layer_height; explicit boundary unit tests                         |
| Performance regression on large meshes                                | Low        | All face ops vectorized via numpy; performance test in suite                                 |
| Gradient algorithm produces visible jumps between stops               | Medium     | Minority-color anchoring verified mathematically; test multi-stop transitions                |
| Config validation incomplete (invalid values accepted)                | Medium     | Comprehensive `validate_config()` with parametrized test cases for all invalid states        |
| 3MF output ZIP structure invalid for slicer import                    | Low        | Boilerplate written per spec; output self-validated after write                              |
| Multi-region clustering misses disconnected islands                   | Medium     | Connected-component analysis on face adjacency; multi-island test fixture                    |
