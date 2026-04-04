# Plan 003 — Slicer-Based Acceptance Tests

## Overview

Implement end-to-end acceptance tests that validate full-spectrum 3MF output by running it through a real slicer binary (OrcaSlicer or BambuStudio), parsing the resulting G-code, and asserting per-layer tool assignments match the expected palette pattern.

**Spec reference:** `specs/003-slicer-acceptance-tests/spec.md`

---

## Phase 1: G-code Parser Utility

**Goal:** Create a standalone G-code parser that extracts per-layer tool assignments, independently testable without a slicer binary.

### Step 1.1 — Create `tests/acceptance/gcode_utils.py`

**File:** `tests/acceptance/gcode_utils.py`

**Function:** `parse_gcode_tool_layers(gcode: str) -> list[tuple[float, int]]`

**Implementation details:**

```python
import re

def parse_gcode_tool_layers(gcode: str) -> list[tuple[float, int]]:
    """Parse G-code and return (z_height, tool_index) for each layer.

    Handles both BambuStudio and OrcaSlicer G-code formats transparently.
    """
```

**Parsing state machine:**

1. Initialize: `current_z = None`, `current_tool = 0`, `layers = []`, `layer_change_pending = False`
2. For each line:
   - If line matches `; CHANGE_LAYER` (BambuStudio) or `;LAYER_CHANGE` (OrcaSlicer): set `layer_change_pending = True`
   - If `layer_change_pending` and line matches `G[01] ... Z<float>` or `;Z:<float>`: extract Z, set `current_z`, clear `layer_change_pending`
   - If line matches `^T(\d+)$` (bare tool change command): set `current_tool` to matched integer
   - After updating Z (new layer detected): if `current_z` differs from last emitted Z, append `(current_z, current_tool)` to `layers`
3. Return `layers`

**Regex patterns:**

```python
RE_LAYER_CHANGE = re.compile(r'^;\s*(?:CHANGE_LAYER|LAYER_CHANGE)', re.IGNORECASE)
RE_Z_MOVE = re.compile(r'^G[01]\s+.*Z([\d.]+)')
RE_Z_COMMENT = re.compile(r'^;Z:([\d.]+)')
RE_TOOL = re.compile(r'^T(\d+)\s*$')
```

**Key edge cases:**
- Tool change may occur before or after layer change — track both independently
- First layer may not have a preceding tool change — default to `T0`
- Only emit when Z actually changes (avoid duplicate entries for same Z)
- Must handle Z in both G-move commands and `;Z:` comment format

### Step 1.2 — Unit tests for G-code parser

**File:** `tests/unit/test_gcode_utils.py`

**Test cases (AC-1, AC-2, AC-3):**

```python
class TestParseGcodeToolLayersBambu:
    def test_basic_layer_tool_sequence(self):
        """AC-1: BambuStudio format with ; CHANGE_LAYER markers."""
        gcode = dedent("""\
            ; CHANGE_LAYER
            G1 Z0.200 F600
            T0
            G1 X10 Y10
            ; CHANGE_LAYER
            G1 Z0.400 F600
            T1
            G1 X20 Y20
        """)
        result = parse_gcode_tool_layers(gcode)
        assert result == [(0.2, 0), (0.4, 1)]

    def test_tool_persists_across_layers(self):
        """Tool stays the same when no T command between layer changes."""

    def test_g0_z_move(self):
        """G0 rapid moves also carry Z changes."""

class TestParseGcodeToolLayersOrcaSlicer:
    def test_basic_orca_format(self):
        """AC-2: OrcaSlicer format with ;LAYER_CHANGE + ;Z: markers."""
        gcode = dedent("""\
            ;LAYER_CHANGE
            ;Z:0.2
            T0
            G1 X10 Y10
            ;LAYER_CHANGE
            ;Z:0.4
            T1
            G1 X20 Y20
        """)
        result = parse_gcode_tool_layers(gcode)
        assert result == [(0.2, 0), (0.4, 1)]

class TestParseGcodeEdgeCases:
    def test_default_tool_is_t0(self):
        """First layer defaults to T0 if no tool change precedes it."""

    def test_no_duplicate_z_entries(self):
        """Multiple commands at same Z height produce only one entry."""

    def test_empty_gcode(self):
        """Empty input returns empty list."""

    def test_mixed_format(self):
        """Parser handles G-code with both marker styles (unlikely but safe)."""
```

### Step 1.3 — Verification checkpoint

```
pytest tests/unit/test_gcode_utils.py -v
```

- All parser unit tests pass
- No slicer binary required
- Covers AC-1, AC-2, AC-3

---

## Phase 2: pytest Configuration

**Goal:** Register the `slicer` marker so tests can be selectively excluded.

### Step 2.1 — Update `pyproject.toml`

**File:** `pyproject.toml`

**Change:** Add marker registration to `[tool.pytest.ini_options]`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "slicer: end-to-end tests requiring a slicer binary (OrcaSlicer or BambuStudio)",
]
```

### Step 2.2 — Verification checkpoint

```
pytest --markers | Select-String "slicer"
```

- Marker appears in output (AC-9)
- No `PytestUnknownMarkWarning` when running tests

---

## Phase 3: Slicer Test Fixtures (conftest)

**Goal:** Create the acceptance test conftest with slicer discovery, profile loading, model generation, and slicing helpers.

### Step 3.1 — Create `tests/acceptance/conftest.py`

**File:** `tests/acceptance/conftest.py`

**Fixtures to implement:**

#### `slicer_bin` fixture (F2, F9)

```python
@pytest.fixture(scope="session")
def slicer_bin() -> tuple[Path, str]:
    """Discover slicer binary from environment variables.

    Returns (path, slicer_type) where slicer_type is "orca" or "bambu".
    Skips all slicer tests if no binary is available.
    """
    for env_var, slicer_type in [
        ("ORCASLICER_BIN", "orca"),
        ("BAMBUSTUDIO_BIN", "bambu"),
    ]:
        path_str = os.environ.get(env_var)
        if path_str:
            p = Path(path_str)
            if p.is_file():
                return (p, slicer_type)
    pytest.skip(
        "No slicer binary available (set ORCASLICER_BIN or BAMBUSTUDIO_BIN)"
    )
```

**Design notes:**
- `scope="session"` — slicer discovery is expensive, do it once
- Checks `ORCASLICER_BIN` first (D1: OrcaSlicer is preferred)
- Validates the file actually exists on disk
- `pytest.skip()` propagates as SKIPPED to all tests using this fixture (AC-4)

#### `slicer_profiles_dir` fixture (F4)

```python
@pytest.fixture(scope="session")
def slicer_profiles_dir() -> Path:
    """Return path to slicer profile fixtures directory."""
    d = Path(__file__).parent.parent / "fixtures" / "slicer_profiles"
    if not (d / "machine.json").exists():
        pytest.skip("Slicer profiles not found at tests/fixtures/slicer_profiles/")
    return d
```

#### `slice_3mf` fixture (F2)

```python
@pytest.fixture(scope="session")
def slice_3mf(slicer_bin, slicer_profiles_dir):
    """Factory fixture: slices a 3MF and returns G-code text."""

    def _slice(input_3mf: Path, output_dir: Path) -> str:
        slicer_path, slicer_type = slicer_bin
        output_3mf = output_dir / "sliced_output.3mf"

        machine_json = slicer_profiles_dir / "machine.json"
        filament_json = slicer_profiles_dir / "filament_pla.json"

        # Build CLI args — note flag differences between slicers
        if slicer_type == "orca":
            export_flag = "--export_3mf"
        else:
            export_flag = "--export-3mf"

        cmd = [
            str(slicer_path),
            "--slice", "1",
            export_flag, str(output_3mf),
            "--load-settings", str(machine_json),
            "--load-filaments", f"{filament_json};{filament_json}",
            str(input_3mf),
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,  # NF4
        )

        if result.returncode != 0:
            pytest.fail(
                f"Slicer failed (exit {result.returncode}):\n"
                f"stdout: {result.stdout[:2000]}\n"
                f"stderr: {result.stderr[:2000]}"
            )

        # Extract G-code from output 3MF ZIP (D5)
        import zipfile
        with zipfile.ZipFile(output_3mf, "r") as zf:
            gcode_candidates = [
                n for n in zf.namelist()
                if n.startswith("Metadata/") and n.endswith(".gcode")
            ]
            if not gcode_candidates:
                pytest.fail(
                    f"No G-code found in output 3MF. ZIP contents: {zf.namelist()}"
                )
            return zf.read(gcode_candidates[0]).decode("utf-8")

    return _slice
```

**Design notes:**
- Factory pattern (returns a callable) — follows existing project convention for parametric fixtures
- Filament loaded twice (`filament_json;filament_json`) to fill both extruder slots
- `timeout=120` per NF4
- Captures stderr for debugging on failure
- Searches `Metadata/` for `.gcode` files rather than hardcoding `plate_1.gcode` for robustness

#### `canonical_prism` fixture (F3)

```python
@pytest.fixture
def canonical_prism(tmp_path):
    """Factory: generates axis-aligned rectangular prism 3MF files.

    Returns a callable: make_prism(height_mm, face_colors, default_filament) -> Path
    """
    def _make(
        height_mm: float,
        face_colors: list[str],
        default_filament: int = 1,
    ) -> Path:
        mesh = trimesh.creation.box(extents=[10, 10, height_mm])
        # Shift so Z range is [0, height_mm] (bottom at Z=0)
        mesh.apply_translation([0, 0, height_mm / 2])

        vertices = np.array(mesh.vertices, dtype=np.float64)
        faces = np.array(mesh.faces, dtype=np.int32)

        out = tmp_path / f"prism_{height_mm}mm.3mf"
        write_3mf(
            out,
            vertices,
            faces,
            face_colors,
            default_filament=default_filament,
            target_format="both",
        )
        return out

    return _make
```

**Design notes:**
- Uses `trimesh.creation.box()` — same pattern as `simple_cube_stl` in existing `conftest.py`
- Explicit `apply_translation` to center the model at Z=height/2 so bottom is at Z=0 — required for deterministic layer boundaries
- Returns a factory, not a single object, because test cases need different heights (4mm, 6mm, 10mm)
- `face_colors` is a `list[str]` of hex codes or empty strings — matches `write_3mf` API signature

### Step 3.2 — Verification checkpoint

```
# With no env vars set:
pytest tests/acceptance/test_e2e_slicer.py -v
```

- All slicer tests show SKIPPED status (AC-4)
- Skip message reads: "No slicer binary available (set ORCASLICER_BIN or BAMBUSTUDIO_BIN)"

---

## Phase 4: Slicer Profiles (Trial-and-Error)

**Goal:** Create minimal JSON profiles that the slicer CLI accepts. This is the most labor-intensive phase.

> **Critical note:** The exact required fields for slicer profiles are uncertain (spec Q2). This phase will require iterative testing against the actual slicer binary. The plan below provides a starting strategy, but expect multiple iterations.

### Step 4.1 — Create `tests/fixtures/slicer_profiles/` directory

**Files to create:**

- `tests/fixtures/slicer_profiles/README.md`
- `tests/fixtures/slicer_profiles/machine.json`
- `tests/fixtures/slicer_profiles/filament_pla.json`

### Step 4.2 — `README.md`

```markdown
# Slicer Test Profiles

Minimal profiles for OrcaSlicer/BambuStudio CLI acceptance tests.

These are user-generated configuration files, not slicer source code.

## machine.json
Generic 2-extruder FDM printer profile. Layer height: 0.2mm.

## filament_pla.json
Minimal PLA filament profile. Loaded twice (once per extruder slot).

## Maintenance
If slicer updates break these profiles, re-export from the slicer GUI
and strip non-essential fields, or examine the slicer's default profiles
in its installation directory (e.g., OrcaSlicer/resources/profiles/).
```

### Step 4.3 — `machine.json` (starting point)

```json
{
    "name": "FullSpectrum Test Printer",
    "type": "machine",
    "from": "system",
    "printer_model": "Generic Printer",
    "nozzle_diameter": "0.4",
    "bed_shape": "0x0,256x0,256x256,0x256",
    "printable_height": "256",
    "extruder_count": "2",
    "layer_height": "0.2",
    "first_layer_height": "0.2",
    "filament_colour": "#FFFFFF;#FFFFFF"
}
```

### Step 4.4 — `filament_pla.json` (starting point)

```json
{
    "name": "FullSpectrum Test PLA",
    "type": "filament",
    "from": "system",
    "filament_type": "PLA",
    "nozzle_temperature": "210",
    "nozzle_temperature_initial_layer": "210",
    "bed_temperature": "60",
    "bed_temperature_initial_layer": "60",
    "filament_id": "fullspectrum_test_pla"
}
```

### Step 4.5 — Iterative validation strategy

This is the key step that cannot be fully specified in advance:

1. **First attempt:** Run slicer CLI with the profiles above on a trivial cube 3MF:
   ```
   $env:ORCASLICER_BIN = "C:\path\to\orca-slicer-console.exe"
   orca-slicer-console --slice 1 --export_3mf output.3mf --load-settings machine.json --load-filaments "filament_pla.json;filament_pla.json" input.3mf
   ```
2. **Read error messages:** Slicer will likely reject the profile with missing-field errors. Add the required fields.
3. **Alternative approach if minimal profiles fail:**
   - Export a full profile from OrcaSlicer GUI (Printer Settings → Export)
   - Examine OrcaSlicer's bundled defaults: `<OrcaSlicer install>/resources/profiles/` 
   - Start with a real profile and iteratively remove fields until the slicer rejects it
4. **Document which fields were required** in the profile README for future maintenance.
5. **Test both slicer types** if both are available — field requirements may differ slightly between OrcaSlicer and BambuStudio.

### Step 4.6 — Verification checkpoint

```powershell
# Manual test: can the slicer CLI slice a simple cube with these profiles?
$slicer = "C:\path\to\orca-slicer-console.exe"
& $slicer --slice 1 --export_3mf test_out.3mf --load-settings tests/fixtures/slicer_profiles/machine.json --load-filaments "tests/fixtures/slicer_profiles/filament_pla.json;tests/fixtures/slicer_profiles/filament_pla.json" test_cube.3mf
# Expected: exit code 0, test_out.3mf contains Metadata/plate_1.gcode
```

---

## Phase 5: Test Case Implementation

**Goal:** Implement the three end-to-end test cases from the spec (F5, F6, F7).

### Step 5.0 — Ensure `tests/acceptance/__init__.py` exists

This file already exists per the spec file layout. Verify it's present.

### Step 5.1 — Create `tests/acceptance/test_e2e_slicer.py`

**File:** `tests/acceptance/test_e2e_slicer.py`

**Imports and common helpers:**

```python
"""End-to-end slicer acceptance tests.

These tests validate full-spectrum 3MF output by running it through a real
slicer binary and asserting the G-code tool assignments match expectations.
"""

import json
from pathlib import Path

import numpy as np
import pytest
import trimesh
from click.testing import CliRunner

from full_spectrum.cli import main
from full_spectrum.encoding import filament_to_hex
from full_spectrum.threemf import write_3mf
from tests.acceptance.gcode_utils import parse_gcode_tool_layers

pytestmark = pytest.mark.slicer
```

**Note:** `pytestmark = pytest.mark.slicer` applies the marker to ALL tests in the module (F8), eliminating the need for per-test `@pytest.mark.slicer` decorators.

#### Helper: run full-spectrum CLI

```python
def _run_full_spectrum(input_path: Path, config: dict, output_path: Path) -> None:
    """Run the full-spectrum CLI via CliRunner (D3)."""
    config_path = output_path.parent / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, [
        str(input_path),
        "-c", str(config_path),
        "-o", str(output_path),
    ])
    assert result.exit_code == 0, f"full-spectrum CLI failed: {result.output}"
```

#### Helper: build expected tool sequence

```python
def _expected_cyclic_sequence(pattern: list[int], n_layers: int) -> list[int]:
    """Build expected tool sequence for a cyclic palette.

    Returns 0-based tool indices (T0, T1, ...) from 1-based filament pattern.
    """
    return [pattern[i % len(pattern)] - 1 for i in range(n_layers)]
```

#### Helper: assert tool sequence with boundary tolerance

```python
def _assert_tool_sequence(
    actual_layers: list[tuple[float, int]],
    expected_tools: list[int],
    tolerance_layers: int = 1,
) -> None:
    """Assert tool sequence matches expected, allowing ±tolerance at boundaries (NF5, D7).

    Compares the interior layers exactly, allows deviation in the first and
    last `tolerance_layers` layers.
    """
    actual_tools = [tool for _, tool in actual_layers]

    # Lengths should be close (within tolerance)
    assert abs(len(actual_tools) - len(expected_tools)) <= tolerance_layers, (
        f"Layer count mismatch: got {len(actual_tools)}, "
        f"expected ~{len(expected_tools)} (±{tolerance_layers})"
    )

    # Compare interior (skip first and last tolerance_layers)
    start = tolerance_layers
    end = min(len(actual_tools), len(expected_tools)) - tolerance_layers
    if end > start:
        actual_interior = actual_tools[start:end]
        expected_interior = expected_tools[start:end]
        assert actual_interior == expected_interior, (
            f"Tool mismatch in interior layers [{start}:{end}]:\n"
            f"  actual:   {actual_interior}\n"
            f"  expected: {expected_interior}"
        )
```

### Step 5.2 — Test F5: 2-Filament Cyclic Alternating

```python
class TestCyclic2Filament:
    """F5: 10×10×4 mm prism, [T0, T1] alternating, 0.2mm layers → 20 layers."""

    def test_alternating_pattern(
        self, canonical_prism, slice_3mf, tmp_path
    ):
        # 1. Generate unpainted model (all faces default filament)
        mesh = trimesh.creation.box(extents=[10, 10, 4])
        mesh.apply_translation([0, 0, 2])
        n_faces = len(mesh.faces)
        face_colors = [""] * n_faces  # unpainted — all default filament

        input_3mf = tmp_path / "input_f5.3mf"
        write_3mf(input_3mf, mesh.vertices, mesh.faces, face_colors,
                   default_filament=1, target_format="both")

        # 2. Run full-spectrum CLI with cyclic [1, 2] palette
        painted_3mf = tmp_path / "painted_f5.3mf"
        config = {
            "layer_height_mm": 0.2,
            "target_format": "both",
            "color_mappings": [{
                "input_filament": 1,
                "output_palette": {"type": "cyclic", "pattern": [1, 2]},
            }],
        }
        _run_full_spectrum(input_3mf, config, painted_3mf)

        # 3. Slice with real slicer
        gcode = slice_3mf(painted_3mf, tmp_path)

        # 4. Parse G-code and assert tool sequence
        layers = parse_gcode_tool_layers(gcode)
        expected = _expected_cyclic_sequence([1, 2], n_layers=20)
        _assert_tool_sequence(layers, expected, tolerance_layers=1)
```

### Step 5.3 — Test F6: 3-Step Cyclic

```python
class TestCyclic3Step:
    """F6: 10×10×6 mm prism, [T0, T0, T1] repeating, 0.2mm layers → 30 layers."""

    def test_three_step_pattern(
        self, canonical_prism, slice_3mf, tmp_path
    ):
        mesh = trimesh.creation.box(extents=[10, 10, 6])
        mesh.apply_translation([0, 0, 3])
        n_faces = len(mesh.faces)
        face_colors = [""] * n_faces

        input_3mf = tmp_path / "input_f6.3mf"
        write_3mf(input_3mf, mesh.vertices, mesh.faces, face_colors,
                   default_filament=1, target_format="both")

        painted_3mf = tmp_path / "painted_f6.3mf"
        config = {
            "layer_height_mm": 0.2,
            "target_format": "both",
            "color_mappings": [{
                "input_filament": 1,
                "output_palette": {"type": "cyclic", "pattern": [1, 1, 2]},
            }],
        }
        _run_full_spectrum(input_3mf, config, painted_3mf)

        gcode = slice_3mf(painted_3mf, tmp_path)

        layers = parse_gcode_tool_layers(gcode)
        expected = _expected_cyclic_sequence([1, 1, 2], n_layers=30)
        _assert_tool_sequence(layers, expected, tolerance_layers=1)
```

### Step 5.4 — Test F7: Two-Region Model

```python
class TestTwoRegion:
    """F7: 10×10×10 mm prism, two painted regions with independent palettes."""

    def test_two_region_assignments(
        self, slice_3mf, tmp_path
    ):
        # Build a box and paint faces by orientation:
        # - Faces with normals pointing in +Z / -Z (top/bottom) → filament 1
        # - Faces with normals pointing in ±X / ±Y (sides) → filament 2
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        mesh.apply_translation([0, 0, 5])

        vertices = np.array(mesh.vertices, dtype=np.float64)
        faces = np.array(mesh.faces, dtype=np.int32)

        # Classify faces by normal direction
        face_colors = []
        for i, face in enumerate(faces):
            normal = mesh.face_normals[i]
            if abs(normal[2]) > 0.5:
                # Top/bottom face → filament 1 (default, empty string)
                face_colors.append("")
            else:
                # Side face → filament 2
                face_colors.append(filament_to_hex(2))

        input_3mf = tmp_path / "input_f7.3mf"
        write_3mf(input_3mf, vertices, faces, face_colors,
                   default_filament=1, target_format="both")

        # Config: filament 1 → cyclic [1,2], filament 2 → stays as filament 2
        painted_3mf = tmp_path / "painted_f7.3mf"
        config = {
            "layer_height_mm": 0.2,
            "target_format": "both",
            "color_mappings": [{
                "input_filament": 1,
                "output_palette": {"type": "cyclic", "pattern": [1, 2]},
            }],
        }
        _run_full_spectrum(input_3mf, config, painted_3mf)

        gcode = slice_3mf(painted_3mf, tmp_path)
        layers = parse_gcode_tool_layers(gcode)

        # The model has both filament 1 and filament 2 regions.
        # Side faces (filament 2) appear at every layer.
        # Top/bottom faces (filament 1) only appear at first/last layers.
        # The slicer must use both T0 and T1 across the model.
        # At minimum, verify we see both tool indices in the output.
        tools_used = {tool for _, tool in layers}
        assert len(tools_used) >= 2, (
            f"Expected at least 2 different tools, got: {tools_used}"
        )
```

**Note on F7 complexity:** The two-region test is less prescriptive about exact per-layer sequences because the slicer's toolpath optimization may reorder tool changes within a layer. The key assertion is that both tool indices appear, confirming the per-triangle filament encoding was correctly decoded by the slicer.

### Step 5.5 — Verification checkpoint

```powershell
# Without slicer:
pytest tests/acceptance/test_e2e_slicer.py -v
# Expected: all tests SKIPPED

# With slicer:
$env:ORCASLICER_BIN = "C:\path\to\orca-slicer-console.exe"
pytest tests/acceptance/test_e2e_slicer.py -v
# Expected: all tests PASSED (AC-5, AC-6, AC-7)

# Marker exclusion:
pytest -m "not slicer" -v
# Expected: slicer tests not collected (AC-8)
```

---

## Phase 6: Integration & Final Verification

### Step 6.1 — Full test suite without slicer

```
pytest -v
```

- All existing tests still pass (no regressions)
- Slicer tests show SKIPPED
- No `PytestUnknownMarkWarning`

### Step 6.2 — Full test suite with slicer

```
$env:ORCASLICER_BIN = "C:\path\to\orca-slicer-console.exe"
pytest -v
```

- Existing tests pass
- Slicer tests pass (AC-5, AC-6, AC-7)

### Step 6.3 — Marker exclusion

```
pytest -m "not slicer" -v
```

- Slicer tests not collected (AC-8)

---

## File Summary

| File | Action | Phase |
|------|--------|-------|
| `tests/acceptance/gcode_utils.py` | Create | 1 |
| `tests/unit/test_gcode_utils.py` | Create | 1 |
| `pyproject.toml` | Edit (add markers) | 2 |
| `tests/acceptance/conftest.py` | Create | 3 |
| `tests/fixtures/slicer_profiles/README.md` | Create | 4 |
| `tests/fixtures/slicer_profiles/machine.json` | Create | 4 |
| `tests/fixtures/slicer_profiles/filament_pla.json` | Create | 4 |
| `tests/acceptance/test_e2e_slicer.py` | Create | 5 |

## Acceptance Criteria Traceability

| AC | Criterion | Covered In |
|----|-----------|-----------|
| AC-1 | BambuStudio G-code parsing | Phase 1, Step 1.2 (`TestParseGcodeToolLayersBambu`) |
| AC-2 | OrcaSlicer G-code parsing | Phase 1, Step 1.2 (`TestParseGcodeToolLayersOrcaSlicer`) |
| AC-3 | Parser tests pass without slicer | Phase 1, Step 1.3 |
| AC-4 | Graceful skip without slicer | Phase 3, Step 3.1 (`slicer_bin` fixture) |
| AC-5 | F5 cyclic 2-filament E2E | Phase 5, Step 5.2 |
| AC-6 | F6 cyclic 3-step E2E | Phase 5, Step 5.3 |
| AC-7 | F7 two-region E2E | Phase 5, Step 5.4 |
| AC-8 | `pytest -m "not slicer"` excludes tests | Phase 5, Step 5.1 (`pytestmark`) + Phase 6, Step 6.3 |
| AC-9 | Marker registered without warnings | Phase 2, Steps 2.1–2.2 |

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Slicer CLI rejects minimal profiles | Blocks Phase 5 | Phase 4 iterative strategy; fallback to exported profiles |
| OrcaSlicer CLI not headless on Windows | Blocks local testing | Try `orca-slicer-console.exe` (headless variant); fall back to BambuStudio |
| G-code format differs from expected | Failing assertions | Parser unit tests (Phase 1) catch this early; add format variants |
| `write_3mf` output incompatible with slicer | Slicer rejects input | Already validated by existing acceptance tests; debug with slicer GUI if needed |
| trimesh box face count varies by version | Wrong `face_colors` length | Assert `len(face_colors) == len(mesh.faces)` in fixture |

## Dependency Order

```
Phase 1 (parser) ─────────────────────┐
Phase 2 (pyproject.toml) ─────────────┤
Phase 3 (conftest fixtures) ──────────┤──→ Phase 5 (test cases) ──→ Phase 6 (integration)
Phase 4 (slicer profiles) ────────────┘
```

Phases 1–4 are independent and can be implemented in parallel. Phase 5 depends on all four. Phase 6 is final validation.
