# Spec 003 — Slicer-Based Acceptance Tests

## Status: Draft

## Context

The `full-spectrum-3mf` project produces 3MF files with per-triangle bisection-encoded filament assignments for Z-layer dithering patterns. The existing test suite covers unit tests (encoding, mesh, config, subdivision), integration tests (pipeline), and CLI acceptance tests — but lacks **slicer-based end-to-end validation**.

The bisection tree encoding format (TriangleSelector) is complex, and bugs in the encoder could be mirrored by an in-project decoder (closed-loop problem). Spec 002 identified a sawtooth artifact that cannot be conclusively verified without an external decoder. A third-party slicer — OrcaSlicer or BambuStudio — is the authoritative decoder of the TriangleSelector bisection format and serves as the ground-truth validator.

This spec defines acceptance tests that run the full pipeline: `full-spectrum` CLI → slicer binary → G-code → assertion on per-layer tool assignments.

## Decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| D1 | Slicer preference | OrcaSlicer primary, BambuStudio fallback | OrcaSlicer is open-source with documented CLI; both share PrusaSlicer lineage and similar G-code output |
| D2 | Profile format | JSON | Both slicers use JSON profiles natively |
| D3 | CLI invocation for full-spectrum step | CliRunner | Existing test pattern in the project, faster than subprocess |
| D4 | CLI invocation for slicer step | `subprocess.run` | Must be a real binary — no mocking — the entire purpose is third-party validation |
| D5 | G-code location in output 3MF | `Metadata/plate_1.gcode` | Standard BambuStudio/OrcaSlicer 3MF packaging convention |
| D6 | Test model geometry | Axis-aligned rectangular prism | All faces axis-aligned; no boundary straddling at clean layer heights; deterministic slicing |
| D7 | Tolerance at boundaries | ±1 layer at top/bottom of model | Slicer may round first/last layer height differently than the analytical expectation |
| D8 | Slicer binary discovery | Environment variables (`ORCASLICER_BIN`, `BAMBUSTUDIO_BIN`) | No Python dependency on slicer; binary is optional external tooling |
| D9 | pytest marker name | `slicer` | Clear intent; registered in `pyproject.toml` to avoid warnings |

## Functional Requirements

### F1: G-code Parser Utility

A module `tests/acceptance/gcode_utils.py` that provides a `parse_gcode_tool_layers()` function.

**Input:** G-code text (string).

**Output:** Ordered list of `(z_height: float, tool_index: int)` events representing the active tool at each layer.

**Parsing rules:**

- **BambuStudio format:**
  - Layer changes marked with `; CHANGE_LAYER` comment (the reserved tag `ETags::Layer_Change`)
  - Z height extracted from `G1 Z<n>` or `G0 Z<n>` moves, or `;Z:<n>` comments
  - Tool changes via `T<n>` commands (`T0`, `T1`, etc.)

- **OrcaSlicer format (PrusaSlicer-compatible):**
  - Layer changes marked with `;LAYER_CHANGE` followed by `;Z:<n>`
  - Tool changes via `T<n>` commands

The parser must handle both formats transparently — a single function that recognizes either style of layer-change marker.

### F2: Slicer Invocation Helper

A fixture or utility that:

1. Discovers the slicer binary from environment variables:
   - `ORCASLICER_BIN` (preferred)
   - `BAMBUSTUDIO_BIN` (fallback)
2. Invokes the slicer on a given 3MF input file with the test profiles
3. Extracts the G-code from the output 3MF ZIP (`Metadata/plate_1.gcode`)
4. Returns the G-code as a string

**CLI invocation patterns:**

```
# OrcaSlicer
orcaslicer --slice 1 --export_3mf output.3mf \
  --load-settings machine.json \
  --load-filaments "filament.json;filament2.json" \
  input.3mf

# BambuStudio
bambu-studio --slice 1 --export-3mf output.3mf \
  --load-settings machine.json \
  --load-filaments "filament.json;filament2.json" \
  input.3mf
```

Note the flag difference: OrcaSlicer uses `--export_3mf` (underscore), BambuStudio uses `--export-3mf` (hyphen).

### F3: Test Fixture — Input Model

A canonical **axis-aligned rectangular prism** (10×10×height mm) generated programmatically or stored as a minimal STL/3MF. The height varies per test case:

- 4 mm for the 2-filament cyclic test (F5)
- 6 mm for the 3-step cyclic test (F6)
- 10 mm for the two-region test (F7)

Axis-alignment ensures no triangle straddles a Z-layer boundary at clean 0.2 mm layer heights, eliminating ambiguity in expected tool assignments.

### F4: Test Fixture — Slicer Profiles

Minimal slicer profiles stored at `tests/fixtures/slicer_profiles/`:

- `machine.json` — Generic 2-filament FDM printer (bed size, nozzle diameter, layer height 0.2 mm)
- `filament_pla.json` — Minimal PLA filament profile (temperature, name)

Profiles are JSON files with required metadata fields: `name`, `type`, `from`. These are user-generated configs, not slicer source code — safe to commit.

### F5: Test Case — 2-Filament Cyclic Alternating

- **Model:** 10×10×4 mm rectangular prism
- **Config:** 2-filament cyclic palette — `[T0, T1]` repeating
- **Layer height:** 0.2 mm → 20 layers
- **Expected tool sequence:** `T0, T1, T0, T1, ...` (alternating every layer)
- **Tolerance:** First and last layer may deviate by 1 position (NF5)
- **Validates:** Basic encoding correctness and single-filament-per-layer dithering

### F6: Test Case — 3-Step Cyclic

- **Model:** 10×10×6 mm rectangular prism
- **Config:** 3-step cyclic palette — `[T0, T0, T1]` repeating
- **Layer height:** 0.2 mm → 30 layers
- **Expected tool sequence:** `T0, T0, T1, T0, T0, T1, ...`
- **Tolerance:** ±1 layer at top/bottom boundaries
- **Validates:** Non-uniform cycle lengths and correct palette indexing

### F7: Test Case — Two-Region Model

- **Model:** 10×10×10 mm rectangular prism with two painted regions (e.g., top half / bottom half, or left/right)
- **Config:** Independent per-filament palettes for each region
- **Layer height:** 0.2 mm → 50 layers
- **Expected:** Each region's layers follow its own palette assignment
- **Validates:** Multi-region encoding and per-triangle filament assignment consistency

### F8: pytest Marker

All slicer acceptance tests are decorated with `@pytest.mark.slicer`.

The marker is registered in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "slicer: end-to-end tests requiring a slicer binary (OrcaSlicer or BambuStudio)",
]
```

This enables `pytest -m "not slicer"` to exclude slicer tests in environments without a slicer binary.

### F9: Auto-Skip Without Slicer

When neither `ORCASLICER_BIN` nor `BAMBUSTUDIO_BIN` is set (or points to a non-existent path), all `@pytest.mark.slicer` tests are automatically skipped with a clear message:

```
SKIPPED: No slicer binary available (set ORCASLICER_BIN or BAMBUSTUDIO_BIN)
```

This is implemented via a pytest fixture in `tests/acceptance/conftest.py` that checks the environment and calls `pytest.skip()`.

## Non-Functional Requirements

| # | Requirement | Detail |
|---|-------------|--------|
| NF1 | No Python slicer dependency | The slicer is an external binary discovered via env var. No slicer Python package is installed. |
| NF2 | Real subprocess invocation | Slicer tests use `subprocess.run`, never mocks. The entire value proposition is third-party validation. |
| NF3 | G-code parser independently testable | `parse_gcode_tool_layers()` is unit-tested with synthetic G-code strings at `tests/unit/test_gcode_utils.py`. These tests require no slicer binary. |
| NF4 | Slicer timeout | `subprocess.run` uses `timeout=120` seconds. On failure, stderr is captured and included in the assertion message. |
| NF5 | Boundary tolerance | Assertions allow ±1 layer deviation at model top and bottom boundaries due to slicer rounding of first/last layer heights. |

## File Layout

```
tests/
  acceptance/
    __init__.py            # existing
    conftest.py            # new: slicer discovery fixture, skip logic
    gcode_utils.py         # new: parse_gcode_tool_layers()
    test_e2e_slicer.py     # new: F5, F6, F7 test cases
  unit/
    test_gcode_utils.py    # new: synthetic G-code unit tests (NF3)
  fixtures/
    slicer_profiles/
      README.md            # instructions for profile files
      machine.json         # minimal generic FDM profile
      filament_pla.json    # minimal PLA filament profile
pyproject.toml             # updated: register slicer marker (F8)
```

## G-code Parsing — Technical Detail

### Layer-Tool Extraction Algorithm

```
initialize current_z = None, current_tool = 0, layers = []
for each line in gcode:
    if line matches layer change marker:
        extract z_height from subsequent Z move or ;Z: comment
        current_z = z_height
    if line matches T<n> command:
        current_tool = n
    if current_z changed and we have a tool:
        append (current_z, current_tool) to layers
return layers
```

### Format Detection

The parser does not require explicit format selection. It recognizes both:
- `; CHANGE_LAYER` (BambuStudio)
- `;LAYER_CHANGE` (OrcaSlicer/PrusaSlicer)

### G-code Inside 3MF ZIP

Both slicers package G-code inside the output 3MF as a ZIP entry:
- Path: `Metadata/plate_<N>.gcode` (typically `plate_1.gcode`)
- The slicer invocation helper extracts this entry using Python's `zipfile` module.

## Relationship to Spec 002

Spec 002 (sub-triangle boundary coloring) identified a sawtooth artifact in the bisection tree encoding. The team cannot conclusively verify encoding correctness using their own decoder because a bug in the encoder could be mirrored by the decoder (closed-loop problem).

Spec 003 breaks this closed loop by using a third-party slicer as the authoritative decoder. Once slicer acceptance tests pass, the encoding is validated against an independent implementation.

The two specs can proceed in parallel:
- Spec 003 is independently valuable — it validates **all** encoding output, not just boundary encoding
- Spec 002 fixes can be verified once spec 003 infrastructure is in place
- A failing slicer test on boundary cases would provide conclusive evidence of spec 002 bugs

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | `parse_gcode_tool_layers()` correctly parses synthetic BambuStudio-format G-code | Unit test with `; CHANGE_LAYER` markers and `T<n>` commands |
| AC-2 | `parse_gcode_tool_layers()` correctly parses synthetic OrcaSlicer-format G-code | Unit test with `;LAYER_CHANGE` / `;Z:<n>` markers |
| AC-3 | G-code parser unit tests pass without any slicer binary | `pytest tests/unit/test_gcode_utils.py` passes in clean env |
| AC-4 | Slicer tests skip gracefully when no slicer binary available | Unset env vars → tests show SKIPPED, exit 0 |
| AC-5 | Test F5 (cyclic 2-filament) passes end-to-end | Alternating T0/T1 pattern verified in slicer G-code output |
| AC-6 | Test F6 (cyclic 3-step) passes end-to-end | T0/T0/T1 repeat pattern verified in slicer G-code output |
| AC-7 | Test F7 (two-region) passes end-to-end | Per-region tool assignments verified in slicer G-code output |
| AC-8 | `pytest -m "not slicer"` excludes all slicer tests | All non-slicer tests pass, slicer tests not collected |
| AC-9 | pytest marker `slicer` registered without warnings | No `PytestUnknownMarkWarning` in test output |

## Open Questions

| # | Question | Status | Resolution |
|---|----------|--------|------------|
| Q1 | Can slicer profiles be committed? | Resolved | Yes — minimal JSON profiles are user-generated configs, no licensing concern |
| Q2 | Minimum required machine profile fields for OrcaSlicer? | Open | Non-blocking; determine during implementation by trial and error with OrcaSlicer CLI |
| Q3 | Does OrcaSlicer CLI work headless on Windows? Does BambuStudio need Xvfb on Linux? | Open | Affects CI configuration only, not test implementation |
