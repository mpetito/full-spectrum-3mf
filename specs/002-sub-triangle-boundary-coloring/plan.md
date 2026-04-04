# Implementation Plan: Sub-Triangle Boundary Coloring

**Spec**: `specs/002-sub-triangle-boundary-coloring/spec.md`
**Date**: 2026-04-03 | **Status**: Ready

---

## Overview

This plan implements opt-in sub-triangle boundary coloring for faces straddling Z-layer boundaries. The feature uses PrusaSlicer's native recursive bisection tree encoding (documented in `specs/001-full-spectrum-3mf/triangle-selector-encoding.md`) to paint boundary faces with two colors — no geometry changes required.

**Key insight**: The `write_3mf()` signature changes from accepting a `face_filaments: np.ndarray` (integers) to `face_colors: list[str]` (hex strings). The pipeline becomes responsible for converting filament indices to hex strings and computing split encodings for boundary faces. This is a clean separation: the writer is format-agnostic, the pipeline owns the logic.

---

## File Change Manifest

| File | Action | Summary |
|------|--------|---------|
| `src/full_spectrum/encoding.py` | **Modify** | Add `BisectionNode`/`LeafNode`/`SplitNode` dataclasses, `encode_bisection_tree()`, `decode_bisection_tree()`, extend `FILAMENT_HEX_TABLE` range documentation |
| `src/full_spectrum/subdivision.py` | **Create** | New module: `find_boundary_faces()`, `compute_split_encoding()`, `encode_boundary_faces()` |
| `src/full_spectrum/pipeline.py` | **Modify** | Integrate boundary splitting, convert `face_filaments` → hex strings, update `PipelineResult` with boundary stats |
| `src/full_spectrum/threemf.py` | **Modify** | Change `write_3mf()` to accept `face_colors: list[str]` instead of `face_filaments: np.ndarray` |
| `src/full_spectrum/config.py` | **Modify** | Add `boundary_split` and `max_split_depth` optional fields to `FullSpectrumConfig`, update `load_config()` and `validate_config()` |
| `src/full_spectrum/cli.py` | **Modify** | Add `--boundary-split`/`--no-boundary-split` and `--max-split-depth` flags, wire through to config and pipeline |
| `tests/unit/test_encoding.py` | **Modify** | Add tests for tree dataclasses, `encode_bisection_tree()`, `decode_bisection_tree()`, round-trip with worked examples |
| `tests/unit/test_subdivision.py` | **Create** | Tests for `find_boundary_faces()`, `compute_split_encoding()`, `encode_boundary_faces()` |
| `tests/unit/test_config.py` | **Modify** | Tests for new config fields (`boundary_split`, `max_split_depth`) |
| `tests/unit/test_threemf.py` | **Modify** | Update `write_3mf()` tests for hex string input |
| `tests/integration/test_pipeline.py` | **Modify** | Add boundary-split pipeline integration tests |
| `tests/integration/test_roundtrip.py` | **Modify** | Add round-trip test with `--boundary-split` |
| `tests/acceptance/test_cli_acceptance.py` | **Modify** | Add CLI acceptance tests for new flags |
| `tests/fixtures/boundary_config.json` | **Create** | Test fixture config with `boundary_split: true` |
| `README.md` | **Modify** | Document `--boundary-split` and `--max-split-depth` usage |

---

## Phase 1: Encoding Foundation

**Goal**: Implement bisection tree data structures and encode/decode functions in `encoding.py`. This is the foundational layer — everything else depends on correct tree serialization.

**Addresses**: FR-2, FR-6, FR-11, DC-1, DC-2, NFR-5, AC-3

### Steps

#### 1.1 Add tree dataclasses to `encoding.py`

Add after the existing `HEX_FILAMENT_TABLE`:

```python
@dataclass
class BisectionNode:
    """A node in the recursive bisection tree."""
    pass

@dataclass
class LeafNode(BisectionNode):
    """Leaf node: no children, represents a triangle region with a single state."""
    state: int  # 0=default, 1=ext1, 2=ext2, ..., 15=ext15

@dataclass
class SplitNode(BisectionNode):
    """Interior split node: bisects one edge, producing 2 child triangles."""
    split_sides: int  # 1 for MVP (always 1-split)
    special_side: int  # edge index (0, 1, or 2) — the edge that IS split
    children: list[BisectionNode]  # 2 children for 1-split
```

**Constraints**: `LeafNode.state` must be 0–15. `SplitNode.split_sides` is always 1 for MVP. `SplitNode.special_side` must be 0, 1, or 2. `SplitNode.children` must have exactly `split_sides + 1` entries.

#### 1.2 Implement `encode_bisection_tree()` in `encoding.py`

```python
def encode_bisection_tree(node: BisectionNode) -> str:
```

Algorithm (from research doc Section 4):
1. DFS traversal: serialize root first, then children in **reverse index order**
2. For each node, emit one nibble: `(xx << 2) | yy`
   - Leaf: `yy=00`, `xx=state` (for state 0–2), or sentinel `0xC` + extra nibble (state 3–15)
   - Split: `yy=split_sides`, `xx=special_side`
3. Collect nibbles into a list
4. Convert each nibble to a hex character
5. **Prepend** each character to the output string (rightmost = root)

**Critical**: The hex string is reversed — root is the rightmost character. See research doc Section 4.1.

#### 1.3 Implement `decode_bisection_tree()` in `encoding.py`

```python
def decode_bisection_tree(hex_str: str) -> BisectionNode:
```

Algorithm (from research doc Section 4.2):
1. Iterate hex string right-to-left (reverse), converting each char to a 4-bit nibble
2. For extended leaves (nibble = `0xC`), consume the next nibble as `state - 3`
3. Use a stack-based DFS to reconstruct the tree:
   - Read nibble → determine node type
   - If split: push expected child count onto stack, recurse
   - If leaf: assign to parent's child slot, pop completed parents

#### 1.4 Unit tests for encode/decode

File: `tests/unit/test_encoding.py` — add new test classes.

**Worked examples from research doc Section 5**:

| Description | Tree Structure | Expected Hex |
|---|---|---|
| Whole triangle, Ext1 | `LeafNode(1)` | `"4"` |
| Whole triangle, Ext2 | `LeafNode(2)` | `"8"` |
| Whole triangle, Ext3 (extended) | `LeafNode(3)` | `"0C"` |
| 1-split, edge 0, children [Ext1, Ext2] | `SplitNode(1, 0, [LeafNode(1), LeafNode(2)])` | `"481"` |
| Nested 2-level split | See Section 5.5 | `"44851"` |

**Round-trip property**: `encode_bisection_tree(decode_bisection_tree(hex)) == hex` for all examples.

**Edge cases**:
- `LeafNode(0)` — default state → `"0"`
- `LeafNode(15)` — maximum extended state → `"CC"` (sentinel C + nibble C=12, state=12+3=15)
- All three edge indices for `special_side` (0, 1, 2)

### Success Criteria

- [ ] `encode_bisection_tree(LeafNode(1))` returns `"4"`
- [ ] `encode_bisection_tree(LeafNode(3))` returns `"0C"`
- [ ] `encode_bisection_tree(SplitNode(1, 0, [LeafNode(1), LeafNode(2)]))` returns `"481"`
- [ ] `decode_bisection_tree("481")` returns the expected tree structure
- [ ] Round-trip holds for all 5 worked examples
- [ ] All existing `test_encoding.py` tests still pass

---

## Phase 2: Subdivision Module

**Goal**: Create `src/full_spectrum/subdivision.py` with boundary face detection and split encoding. This is the geometric intelligence layer.

**Addresses**: FR-1, FR-2, FR-3, FR-7, FR-8, DC-2, DC-3, DC-5, NFR-1, NFR-4, AC-9

### Steps

#### 2.1 Create `src/full_spectrum/subdivision.py`

##### `find_boundary_faces()`

```python
def find_boundary_faces(
    mesh: trimesh.Trimesh,
    layer_indices: np.ndarray,
    layer_height: float,
    global_z_min: float,
) -> np.ndarray:
```

Algorithm (vectorized, O(n)):
1. For each face, compute the layer band from `layer_indices[i]`:
   - `band_low = global_z_min + layer_indices[i] * layer_height`
   - `band_high = band_low + layer_height`
2. Get per-face vertex Z coordinates: `mesh.vertices[mesh.faces][:, :, 2]` → shape `(F, 3)`
3. Compute per-face `z_min = vert_z.min(axis=1)`, `z_max = vert_z.max(axis=1)`
4. A face is a boundary face if `z_min < band_low - epsilon` OR `z_max > band_high + epsilon`
5. Return boolean mask of shape `(F,)`

**Key**: `layer_indices` are the centroid-based assignments from the existing pipeline. `global_z_min` is `mesh.vertices[:, 2].min()`. Epsilon = `layer_height * 0.001` (matching existing `mesh.py` convention).

##### `subdivide_triangle()` — Recursive Convergence

```python
def subdivide_triangle(
    vertices: np.ndarray,          # shape (3, 3) — triangle vertices
    layer_height: float,
    global_z_min: float,
    palette_by_layer: np.ndarray,  # filament for each layer index
    max_depth: int = 12,
    epsilon: float = ...,          # layer_height * 0.001
) -> BisectionNode:
```

This is the core algorithm. It recursively subdivides a triangle until every leaf fits within a single layer band.

**Algorithm**:
1. Compute the Z-span of the triangle: `z_lo = min(v[:,2])`, `z_hi = max(v[:,2])`.
2. Compute which layer bands the triangle spans: `layer_lo = floor((z_lo - global_z_min + eps) / layer_height)`, `layer_hi = floor((z_hi - global_z_min + eps) / layer_height)`.
3. **Base case — convergence**: If `layer_lo == layer_hi`, the triangle fits within one layer band. Return `LeafNode(palette_by_layer[layer_lo])`.
4. **Base case — depth cap**: If `max_depth == 0`, the triangle cannot be split further. Return `LeafNode(palette_by_layer[centroid_layer])` (fall back to centroid assignment).
5. **Recursive case**: The triangle spans multiple layers. Find the Z boundary closest to the triangle's midpoint Z (or closest to the best-fit edge midpoint).
   a. Identify layer boundaries within the triangle's Z-span: `boundaries = [global_z_min + k * layer_height for k in range(layer_lo + 1, layer_hi + 1)]`.
   b. **Edge selection (DC-3)**: For each edge (0, 1, 2), compute midpoint Z. Select the edge whose midpoint Z is closest to any of the layer boundaries within the triangle's Z-span.
   c. Compute the midpoint `M` of the selected edge. Determine the two child vertex sets:
      - Child 0 vertices: `[v[e], M, v[(e+2)%3]]`
      - Child 1 vertices: `[M, v[(e+1)%3], v[(e+2)%3]]`
      (Following PrusaSlicer 1-split convention from research doc Section 3.2)
   d. Recurse on both children with `max_depth - 1`.
   e. Return `SplitNode(split_sides=1, special_side=best_edge, children=[child_0_node, child_1_node])`.

**Convergence analysis**: For a triangle spanning N layers, each 1-split roughly halves the Z-span of the larger child. The tree depth is ≈ log₂(N). For a 20mm cube face at 0.1mm layers (N=200), depth ≈ 8, producing ~256 leaf nodes. The hex string is ~256×1 + ~255×1 = ~511 nibbles ≈ 511 hex chars. This is well within slicer limits.

##### `encode_boundary_faces()`

```python
def encode_boundary_faces(
    mesh: trimesh.Trimesh,
    face_filaments: np.ndarray,
    layer_indices: np.ndarray,
    layer_height: float,
    global_z_min: float,
    palette_by_layer: np.ndarray,  # shape (max_layer+1,) — filament for each layer index
    max_depth: int = 12,
) -> dict[int, str]:
```

Orchestrator:
1. Call `find_boundary_faces()` to get boundary mask.
2. Compute `epsilon = layer_height * 0.001`.
3. For each boundary face `i`:
   a. Extract vertex coordinates: `verts = mesh.vertices[mesh.faces[i]]` — shape (3, 3).
   b. Call `subdivide_triangle(verts, layer_height, global_z_min, palette_by_layer, max_depth, epsilon)` to get the bisection tree.
   c. Call `encode_bisection_tree(tree)` to get the hex string.
4. Return `{face_index: hex_string}` for boundary faces only.

**Interior faces are untouched** (FR-7): Only faces where `find_boundary_faces()` returns True are processed. All others keep their whole-triangle hex code.

#### 2.2 Unit tests for subdivision

File: `tests/unit/test_subdivision.py` (new)

**`find_boundary_faces()` tests**:
- Synthetic mesh: 4 triangles forming a vertical strip. Two triangles entirely within a layer band → not boundary. Two triangles crossing a layer boundary → boundary.
- All-interior mesh → empty mask.
- Single triangle exactly on boundary (epsilon test) → not boundary (within epsilon).

**`subdivide_triangle()` tests — convergence cases**:
- Triangle spanning 1 layer (z_span < layer_height) → returns LeafNode, no split.
- Triangle spanning 2 layers (z_span ≈ 1.5 × layer_height) → 1 split, 2 leaves, each in one layer.
- Triangle spanning 4 layers → depth 2, ~4 leaves, each fitting in one layer.
- **Cube face test**: Triangle from Z=0 to Z=2mm at layer_height=0.1mm (20 layers) → tree converges with all leaves fitting in single layer bands. Decode tree and verify each leaf's filament matches `palette_by_layer` for its layer.
- **Cube face test (deep)**: Triangle from Z=0 to Z=20mm at layer_height=0.1mm (200 layers) → tree depth ≈ 8, ~256 leaves. Verify convergence: all leaves are within-layer.
- `max_depth=0` → returns whole-triangle leaf (no split, centroid fallback).
- Edge selection: construct triangle where edge 1's midpoint Z is closest to nearest boundary → `special_side=1`.

**`encode_boundary_faces()` tests**:
- Small synthetic mesh with known geometry. Verify returned dict contains only boundary face indices.
- Verify all returned hex strings decode to valid bisection trees.
- Verify every leaf in every decoded tree maps to the correct layer's filament.

### Success Criteria

- [ ] `find_boundary_faces()` correctly identifies boundary faces on synthetic geometry
- [ ] `find_boundary_faces()` returns empty mask for all-interior mesh
- [ ] `subdivide_triangle()` converges: every leaf fits within one layer band
- [ ] Cube face triangle (200 layers) fully resolves — all leaves correct
- [ ] Edge selection picks the edge with midpoint Z closest to nearest boundary
- [ ] `max_depth=0` produces a leaf-only encoding (centroid fallback)
- [ ] `encode_boundary_faces()` returns dict with only boundary face indices
- [ ] All returned hex strings are valid (round-trip through decode)

---

## Phase 3: Pipeline & Writer Integration

**Goal**: Wire subdivision into the pipeline and update `write_3mf()` to accept hex strings. This is the integration layer where everything connects.

**Addresses**: FR-4, FR-7, FR-9, FR-10, DC-6, DC-7, AC-1, AC-2, AC-4

### Steps

#### 3.1 Change `write_3mf()` signature in `threemf.py`

**Before**:
```python
def write_3mf(output_path, vertices, faces, face_filaments: np.ndarray, default_filament=1, target_format="both")
```

**After**:
```python
def write_3mf(output_path, vertices, faces, face_colors: list[str], default_filament=1, target_format="both")
```

Changes inside `write_3mf()`:
- Replace `filament = int(face_filaments[i])` + `filament_to_hex(filament)` with `hex_code = face_colors[i]`
- A face gets color attributes only if `hex_code` is non-empty and the face is not the default filament. Determine "is default" by checking if `hex_code == ""` or `hex_code == filament_to_hex(default_filament)`. Simpler: pass empty string `""` for default-filament faces, and write the attribute for any non-empty `hex_code`.
- Remove import of `filament_to_hex` from threemf.py (no longer needed there).

**Backward compatibility**: The pipeline is responsible for converting `face_filaments` to hex strings before calling `write_3mf()`. When `--boundary-split` is off, each face gets `filament_to_hex(face_filaments[i])` or `""` for default.

#### 3.2 Update pipeline `process()` in `pipeline.py`

After Step 4 (palette application), add boundary split logic:

```python
# Step 5: Convert to hex strings
from full_spectrum.encoding import filament_to_hex

face_hex: list[str] = []
for i in range(n_faces):
    fil = int(face_filaments[i])
    if fil == default_filament:
        face_hex.append("")
    else:
        face_hex.append(filament_to_hex(fil))

# Step 5b: Boundary splitting (if enabled)
boundary_face_count = 0
if config.boundary_split:
    from full_spectrum.subdivision import encode_boundary_faces, find_boundary_faces

    global_z_min = mesh.vertices[:, 2].min()
    all_layer_indices = compute_face_layers(mesh, config.layer_height_mm)

    # Build palette_by_layer: for each global layer index, what filament is assigned?
    # This requires computing the mapping from global layer → filament.
    # Use face_filaments: group by layer, take mode (most common filament per layer).
    max_layer = int(all_layer_indices.max())
    palette_by_layer = np.full(max_layer + 2, default_filament, dtype=np.int32)
    for layer_idx in range(max_layer + 1):
        mask = all_layer_indices == layer_idx
        if mask.any():
            vals, counts = np.unique(face_filaments[mask], return_counts=True)
            palette_by_layer[layer_idx] = vals[counts.argmax()]

    boundary_splits = encode_boundary_faces(
        mesh, face_filaments, all_layer_indices,
        config.layer_height_mm, global_z_min,
        palette_by_layer, config.max_split_depth,
    )
    boundary_face_count = len(boundary_splits)

    for face_idx, hex_str in boundary_splits.items():
        face_hex[face_idx] = hex_str
```

Update the `write_3mf()` call:
```python
write_3mf(output_path, mesh.vertices, mesh.faces, face_hex,
          default_filament=default_filament, target_format=config.target_format)
```

#### 3.3 Update `PipelineResult`

Add boundary face statistics:

```python
@dataclass
class PipelineResult:
    success: bool
    face_count: int = 0
    layer_count: int = 0
    filament_distribution: dict[int, int] = field(default_factory=dict)
    boundary_face_count: int = 0
    boundary_face_pct: float = 0.0
    warnings: list[str] = field(default_factory=list)
```

Set `boundary_face_count` and `boundary_face_pct` in the pipeline after boundary splitting.

#### 3.4 Update existing tests

- **`tests/unit/test_threemf.py`**: Update `write_3mf()` calls to pass `face_colors: list[str]` instead of `face_filaments: np.ndarray`. The existing tests construct face_filaments arrays — convert them to hex string lists.
- **`tests/integration/test_pipeline.py`**: Verify pipeline still works with `boundary_split=False` (default). Add a test with `boundary_split=True` on a simple mesh.
- **`tests/integration/test_roundtrip.py`**: Verify round-trip with and without boundary splitting.

### Success Criteria

- [ ] `write_3mf()` accepts `face_colors: list[str]` and writes correct XML attributes
- [ ] Pipeline produces hex string list and passes to writer
- [ ] `boundary_split=False` output is byte-identical to spec 001 behavior (AC-2)
- [ ] `boundary_split=True` produces multi-nibble hex on boundary faces (AC-1)
- [ ] `PipelineResult` reports `boundary_face_count` and `boundary_face_pct` (AC-4)
- [ ] All existing tests pass after signature change

---

## Phase 4: CLI & Config

**Goal**: Expose `--boundary-split` and `--max-split-depth` in the CLI and config file. Wire override logic (CLI > config > defaults).

**Addresses**: FR-4, FR-5, DC-4, AC-11, AC-12

### Steps

#### 4.1 Add fields to `FullSpectrumConfig` in `config.py`

```python
@dataclass(frozen=True)
class FullSpectrumConfig:
    layer_height_mm: float
    target_format: str
    color_mappings: list[ColorMapping]
    boundary_split: bool = False
    max_split_depth: int = 12
```

Update `load_config()` to parse optional fields:
```python
boundary_split = raw.get("boundary_split", False)
max_split_depth = raw.get("max_split_depth", 12)
```

Update `validate_config()`:
- `max_split_depth` must be >= 0 (AC-12: depth 0 = no splitting)
- `max_split_depth` > 16 → warning (likely unnecessary, slicer tree depth limit)

Update `default_config()` to accept and pass through `boundary_split` and `max_split_depth`.

#### 4.2 Add CLI flags in `cli.py`

```python
@click.option("--boundary-split/--no-boundary-split", default=None,
              help="Enable sub-triangle encoding for faces straddling layer boundaries.")
@click.option("--max-split-depth", type=int, default=None,
              help="Maximum bisection depth for boundary splits (default: 1).")
```

Note: `default=None` so we can distinguish "not provided" from "explicitly False/0". Override logic:
1. If CLI flag is provided, use it.
2. Else if config file has the field, use config value.
3. Else use default (`False` / `12`).

Wire into config construction — when building or overriding `FullSpectrumConfig`, propagate these fields.

#### 4.3 Verbose output for boundary stats

In `cli.py`, after pipeline returns, if `verbose` and `result.boundary_face_count > 0`:
```python
click.echo(f"Boundary faces: {result.boundary_face_count} ({result.boundary_face_pct:.1f}%)")
```

#### 4.4 Update tests

- **`tests/unit/test_config.py`**: Test `load_config()` with and without `boundary_split`/`max_split_depth` fields. Test validation of `max_split_depth` range.
- **`tests/fixtures/boundary_config.json`**: Create fixture with `"boundary_split": true, "max_split_depth": 12`.
- **`tests/acceptance/test_cli_acceptance.py`**: Test `--boundary-split` flag is accepted. Test `--max-split-depth 0` produces no boundary splits (AC-12). Test `--boundary-split --max-split-depth 2` is accepted.

### Success Criteria

- [ ] Config loads `boundary_split` and `max_split_depth` from JSON (AC-11)
- [ ] CLI `--boundary-split` enables feature; `--no-boundary-split` disables
- [ ] CLI flags override config file values (AC-11)
- [ ] `--max-split-depth 0` is equivalent to `--no-boundary-split` (AC-12)
- [ ] Verbose output reports boundary face count and percentage (AC-4)
- [ ] Existing CLI tests pass unchanged

---

## Phase 5: Integration Testing & Verification

**Goal**: End-to-end validation of the complete feature. Verify backward compatibility, performance, and multi-boundary face handling.

**Addresses**: FR-8, FR-10, NFR-2, NFR-3, NFR-4, AC-1, AC-2, AC-8, AC-9, AC-10

### Steps

#### 5.1 Backward compatibility test (AC-2, FR-10)

- Process the same STL with identical config, once with `--boundary-split` disabled (default).
- Compare output byte-for-byte with spec 001 reference output.
- Verify no regression in existing test suite.

#### 5.2 Boundary split integration test (AC-1)

- Process a sample STL (e.g., `samples/cylinder.stl` or `samples/3dbenchy.3mf`) with `--boundary-split`.
- Parse the output 3MF and verify:
  - Interior faces have single-nibble or 2-nibble hex codes (whole-triangle).
  - Boundary faces have 3+ nibble hex codes (split tree).
  - All hex codes round-trip through `decode_bisection_tree()`.
  - Every leaf sub-triangle in the decoded tree fits within a single layer band.

#### 5.3 Cube convergence test (AC-9)

- Create a simple cube mesh (12 faces, or even 2 triangles for one face) with height 2mm at layer_height=0.1mm (20 layers per face triangle).
- Process with `--boundary-split` and verify:
  - Each boundary face produces a deep tree (depth ≈ 5-6 for 20 layers).
  - Every leaf in the decoded tree maps to the correct layer's filament.
  - No centroid-fallback leaves (all converged within depth 12 cap).

#### 5.4 Performance test (AC-8, NFR-2, NFR-3)

- Generate or use a 100k-face mesh.
- Time the pipeline with `--boundary-split`:
  - Total time < 15 seconds on commodity hardware.
  - For well-tessellated meshes (low boundary fraction), overhead should be modest.
- Separately test coarse geometry (cube) to verify it completes quickly regardless of deep trees.
- This can be a pytest benchmark or a simple wall-clock assertion.

#### 5.5 Multi-boundary face test (FR-8)

- Construct a synthetic triangle with vertices spanning 3+ layers (very large Z extent relative to layer height).
- Process with `--boundary-split`: verify the tree converges — all leaves fit within one layer band.
- Verify the tree depth is approximately log₂(Z_span / layer_height).
- With `--max-split-depth 2`: verify partial convergence and centroid fallback for unconverged leaves.

#### 5.6 Flatten flag compatibility (AC-10)

- Verify `--flatten` still works for sub-painted input files.
- Process a sub-painted 3MF with `--flatten`, confirm it flattens to whole-triangle codes.
- Then process the flattened output with `--boundary-split`, confirm it produces split codes.

#### 5.7 Slicer compatibility notes (AC-5, AC-6, AC-7)

AC-5, AC-6, AC-7 require manual verification in PrusaSlicer, BambuStudio, and OrcaSlicer respectively. Add a note in the test file documenting the manual verification procedure:
1. Open the output 3MF in each slicer.
2. Verify no import errors.
3. Zoom into a layer boundary area and confirm sub-painted regions are visible.
4. Slice and verify no slicing errors.

### Success Criteria

- [ ] Without `--boundary-split`, output matches spec 001 byte-for-byte (AC-2)
- [ ] With `--boundary-split`, boundary faces have multi-nibble hex strings (AC-1)
- [ ] Cube model: all leaves converge to single-layer bands (AC-9)
- [ ] 100k-face mesh with `--boundary-split` completes in < 15s (AC-8)
- [ ] Partial depth cap: unconverged leaves fall back to centroid (FR-8)
- [ ] `--flatten` still works (AC-10)
- [ ] All existing tests pass

---

## Phase 6: Documentation

**Goal**: Update user-facing documentation to describe the new feature.

**Addresses**: (Documentation completeness)

### Steps

#### 6.1 Update `README.md`

Add a section on boundary splitting:
- What it does (eliminates visible banding at layer boundaries)
- How to enable (`--boundary-split`)
- How to control depth (`--max-split-depth`)
- Example command

#### 6.2 Update CLI help text

Already handled by click option `help=` parameters in Phase 4.

#### 6.3 Add boundary-split config example

Create `docs/examples/boundary_split.json`:
```json
{
  "layer_height_mm": 0.08,
  "target_format": "both",
  "boundary_split": true,
  "max_split_depth": 12,
  "color_mappings": [
    {
      "input_filament": 1,
      "output_palette": { "type": "cyclic", "pattern": [1, 2] }
    }
  ]
}
```

### Success Criteria

- [ ] README documents `--boundary-split` and `--max-split-depth`
- [ ] Example config file is valid JSON and loads without error
- [ ] `--help` output includes new flags

---

## Requirement Traceability Matrix

| Requirement | Phase | Steps | Verification |
|---|---|---|---|
| FR-1: Boundary face detection | Phase 2 | 2.1 (`find_boundary_faces`) | Unit tests, Phase 5.2 |
| FR-2: Bisection tree encoding | Phase 1, 2 | 1.2, 1.3, 2.1 (`subdivide_triangle`) | Worked examples, round-trip tests, cube convergence |
| FR-3: Automatic convergence depth | Phase 2, 4 | 2.1 (`subdivide_triangle`, `max_depth`), 4.1, 4.2 | Cube test, AC-12 |
| FR-4: Opt-in behavior | Phase 4 | 4.2 (`--boundary-split`) | AC-1, AC-2 |
| FR-5: Config file integration | Phase 4 | 4.1 (`load_config`) | AC-11 |
| FR-6: Slicer compatibility | Phase 1 | 1.2, 1.3 (format compliance) | AC-5, AC-6, AC-7 (manual) |
| FR-7: Interior faces unchanged | Phase 2, 3 | 2.1 (mask), 3.2 (hex list) | Unit tests, integration |
| FR-8: Multi-boundary handling | Phase 2 | 2.1 (`encode_boundary_faces`) | AC-9, Phase 5.4 |
| FR-9: Variable-length hex output | Phase 3 | 3.1 (`write_3mf` signature) | Unit + integration tests |
| FR-10: Backward compatibility | Phase 3 | 3.2 (flag-off path) | AC-2, Phase 5.1 |
| FR-11: Encoding module extensions | Phase 1 | 1.1–1.3 | Unit tests |
| NFR-1: O(n) detection | Phase 2 | 2.1 (vectorized) | Code review |
| NFR-2: Overhead budget | Phase 5 | 5.4 | Benchmark |
| NFR-3: 100k faces <15s | Phase 5 | 5.4 | Timed test (AC-8) |
| NFR-4: 1–5% boundary ratio | Phase 2, 5 | 2.1 (fast path), 5.3 | Benchmark |
| NFR-5: Test coverage | Phase 1–5 | All test steps | Test runner |

---

## Testing Strategy

### Unit Tests (Phases 1–4)
- **`test_encoding.py`**: Tree dataclass construction, encode/decode round-trips, all 5 worked examples, extended leaves (state 3–15), edge cases (state 0, state 15)
- **`test_subdivision.py`**: Boundary detection on synthetic meshes, recursive convergence (cube face spanning many layers), edge selection, depth cap fallback, depth 0 = no split
- **`test_config.py`**: New fields parsed, validated, defaults applied (12), CLI override
- **`test_threemf.py`**: Updated write_3mf calls with hex string input

### Integration Tests (Phase 5)
- **`test_pipeline.py`**: End-to-end with boundary split on/off, PipelineResult stats
- **`test_roundtrip.py`**: STL → 3MF → parse → verify hex codes

### Acceptance Tests (Phase 5)
- **`test_cli_acceptance.py`**: CLI flag parsing, output file creation, verbose output
- **Manual**: Slicer import verification (PrusaSlicer, BambuStudio, OrcaSlicer)

### Performance Tests (Phase 5)
- 100k face mesh, wall-clock < 12s with boundary split
- Overhead measurement: baseline vs boundary-split time ratio

---

## Risk & Mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| Hex encoding produces invalid tree | Slicer crash on import | Extensive round-trip tests against worked examples from PrusaSlicer source |
| Child triangle vertex computation wrong | Incorrect split geometry, non-converging recursion | Unit test with deterministic geometry where child vertices are hand-computable |
| Child triangle assignment wrong (below/above swap) | Incorrect colors at boundaries | Unit test with known geometry where correct assignment is deterministic |
| `write_3mf` signature change breaks callers | Regression in spec 001 behavior | Byte-identical backward compatibility test (AC-2) |
| Performance regression on large meshes | Exceeds 15s budget | Vectorized boundary detection, per-face tree building only for boundary faces (1–5% of total) |
| Deep trees for coarse meshes | Long hex strings, potential slicer limits | Test with cube at fine layer height; verify slicer imports correctly; cap at depth 12 |
| Edge selection picks wrong edge | Suboptimal split precision, slower convergence | Unit test verifying midpoint-Z proximity criterion |
| `palette_by_layer` computation wrong | Incorrect adjacent-layer filament | Test with known cyclic pattern where each layer's filament is deterministic |
