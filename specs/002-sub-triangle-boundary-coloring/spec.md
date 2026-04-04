# Spec: Sub-Triangle Boundary Coloring

**Date**: 2026-04-03 | **Status**: Draft

## Context

The full-spectrum-3mf CLI pre-processes 3MF files for Full Spectrum 3D printing. Spec 001 delivered the MVP with whole-triangle centroid-based layer assignment. Two items were explicitly deferred:

1. **Sub-Triangle Precision**: No sub-triangle recursive bisection encoding; whole-triangle coloring only.
2. **Advanced Mesh Subdivision**: Mesh slicing at Z-plane boundaries (Strategy C) deferred to v1.1.

After analysis, **sub-triangle boundary coloring** is the correct path forward — not mesh subdivision.

The `mmu_segmentation` / `paint_color` attribute in 3MF already supports recursive bisection trees. This is the same format the slicer paint brush uses internally. Whole-triangle assignments (`"4"`, `"8"`, `"0C"`) are degenerate cases (leaf-only trees). The tool can encode boundary splits as short multi-nibble hex strings on the same triangle elements — zero geometry changes required.

A detailed research document on the TriangleSelector encoding format is available at `specs/001-full-spectrum-3mf/triangle-selector-encoding.md`.

### Why Sub-Triangle Coloring Over Mesh Subdivision

| Criterion | Mesh Subdivision | Sub-Triangle Coloring |
|---|---|---|
| Triangle count impact | 10–50× multiplication | Zero change |
| Slicer import performance | Degrades quadratically | No impact |
| Boundary precision | Exact | Very high (~2–3 levels ≈ <0.01 mm at 0.08 mm layer) |
| Output file size | Large (more vertices/triangles) | Small (longer hex strings) |
| Slicer compatibility | Any slicer | Same slicers already targeted |
| Round-trip safety | Geometry intact | Sub-painted data merged correctly by slicer tools |

Sub-triangle coloring achieves the same visual result without performance regression. Mesh subdivision (Strategy C) is formally dropped from the roadmap.

## Objective

Enable boundary-straddling triangles to be encoded with multiple colors using the slicer's native recursive bisection tree format. This eliminates visible color banding at layer boundaries without increasing triangle count or degrading slicer performance.

The feature is opt-in. Default behavior remains identical to spec 001 (whole-triangle centroid assignment).

## Scope

### In Scope

- Boundary face detection after centroid-based layer assignment
- Bisection tree encoding for boundary faces (1-split per level, configurable depth)
- `--boundary-split` / `--no-boundary-split` CLI flag
- `--max-split-depth` CLI flag (default 1)
- Config file fields: `boundary_split`, `max_split_depth`
- New `subdivision.py` module for boundary detection and tree building
- Extensions to `encoding.py` for bisection tree encode/decode
- `write_3mf()` signature update to accept variable-length hex strings per face
- Verbose output reporting boundary face statistics
- Unit tests for encode/decode round-trips, boundary detection, and worked examples

### Out of Scope

- Mesh subdivision / geometry modification (Strategy C — dropped)
- 2-split and 3-split node types (only 1-split is used; recursive 1-splits achieve the same granularity)
- Sub-painted INPUT handling changes (`is_sub_painted()` guard and `--flatten` remain as-is)
- Changes to `mesh.py` or `palette.py`
- GUI or interactive boundary preview

## Requirements

### Functional

**FR-1: Boundary Face Detection**
After centroid-based layer assignment, identify faces whose vertex Z-span crosses the assigned layer's boundaries. A face is a "boundary face" if any vertex lies outside the centroid's layer band, accounting for epsilon tolerance. Detection must operate on the existing mesh data without modifying geometry.

**FR-2: Recursive Bisection Tree Encoding**
For each boundary face, recursively subdivide via 1-splits until every leaf sub-triangle's vertex Z-span fits within a single layer band (within epsilon tolerance). At each level, select the edge whose midpoint Z is closest to the nearest unresolved layer boundary. Assign each leaf the filament for the layer containing its centroid. Encode the resulting tree as a PrusaSlicer-compatible bisection tree hex string. The encoding must follow the TriangleSelector format exactly.

**Convergence rationale**: Consider a cube — each face is just 2 triangles spanning the full model height. A 20 mm cube at 0.1 mm layer height has 200 layer boundaries per face-triangle. A single split is grossly insufficient. The tree must recurse to depth ≈ log₂(Z_span / layer_height) — about 8 levels for this example — producing ~256 leaf sub-triangles per face, each fitting within one layer band.

**FR-3: Automatic Convergence with Safety Cap**
Bisection depth is determined automatically: recursion continues until every leaf sub-triangle's Z-span is within the layer band tolerance (epsilon = 0.1% of layer_height). A `--max-split-depth` safety cap (default 12) prevents runaway recursion on degenerate geometry. Depth 12 supports Z-span / layer_height ratios up to ~4096, far exceeding any practical model.

**FR-4: Opt-In Behavior**
A `--boundary-split` CLI flag enables sub-triangle encoding. Default is off. When disabled, output is byte-identical to spec 001 behavior.

**FR-5: Config File Integration**
JSON config supports optional `boundary_split: bool` and `max_split_depth: int` fields. CLI flags override config values. Omitted fields fall back to defaults (`false`, `12`).

**FR-6: Output Slicer Compatibility**
Generated hex strings must be parseable by PrusaSlicer, BambuStudio, and OrcaSlicer. The encoding follows the exact TriangleSelector recursive bisection format documented in the research doc.

**FR-7: Interior Faces Unchanged**
Only boundary faces receive sub-triangle encoding. Interior faces (all vertices within a single layer band) retain their whole-triangle hex code. The output is a mix of simple leaf codes and multi-nibble tree codes.

**FR-8: Multi-Boundary Face Handling**
Faces spanning many layer boundaries (e.g., cube-face triangles spanning the full model height) are the primary use case, not an edge case. Recursive 1-splits continue until convergence (every leaf fits within one layer band) or `max_split_depth` is reached. If the depth cap is hit before full convergence, remaining leaves fall back to centroid-layer assignment. With the default cap of 12, this only occurs for Z-span / layer_height > 4096.

**FR-9: Variable-Length Hex Output**
`write_3mf()` must accept variable-length hex strings per face — not only filament integers. The data structure passed from the pipeline to the writer changes from a 1D int array to a sequence of hex strings (or equivalent).

**FR-10: Backward Compatibility**
Output produced with `--boundary-split` disabled must be byte-identical to spec 001 output for the same input and configuration.

**FR-11: Encoding Module Extensions**
New functions: `encode_bisection_tree()`, `decode_bisection_tree()`, and supporting tree data structures. These live in `encoding.py` (tree encode/decode) and/or a new `subdivision.py` module (boundary detection, tree building).

### Non-Functional

**NFR-1: Performance — Boundary Detection**
Boundary face detection must be O(n) in face count. No spatial indexing or neighbor traversal required — a per-face vertex Z-range check against layer boundaries suffices.

**NFR-2: Performance — Total Overhead**
Sub-triangle encoding overhead scales with the number of boundary faces and average tree depth. For well-tessellated meshes (1–5% boundary faces, avg depth ~3), overhead should be under 50% of baseline. For coarse meshes like cubes (high boundary fraction, deep trees), overhead can be up to 2–3× baseline but must remain linear in total leaf count.

**NFR-3: Performance — Large Mesh**
A well-tessellated 100k-face mesh processed with `--boundary-split` must complete in under 15 seconds on commodity hardware. A coarse mesh (e.g., cube with 12 faces, deep trees) must complete in under 5 seconds regardless of model height.

**NFR-4: Boundary Face Fraction**
For well-tessellated meshes at typical layer heights (0.08–0.12 mm), boundary faces are expected to be 1–5% of total faces. The implementation should be optimized for this ratio (vectorized interior-face fast path, per-face tree building only for boundary faces).

**NFR-5: Test Coverage**
Unit tests must cover: bisection tree encode/decode round-trips, boundary detection with known geometry, worked examples from the research document, multi-boundary face degradation, and backward compatibility (flag-off identity).

## Design Constraints

**DC-1: TriangleSelector Encoding Format**
The PrusaSlicer TriangleSelector format must be followed exactly:
- Each tree node = one 4-bit nibble
- Node format: `bits[1:0]` = split type (00=leaf, 01=1-split, 10=2-split, 11=3-split); `bits[3:2]` = state (for leaves) or special_side (for splits)
- Tree traversal: depth-first, children serialized in reverse index order
- Hex string is **reversed**: rightmost character = root node
- Leaf states: 0=default, 1=ext1, 2=ext2, 3+ = extended 2-nibble encoding
- Edge indices: 0 = v0→v1, 1 = v1→v2, 2 = v2→v0

**DC-2: 1-Split Node Type, Recursive Depth**
Only 1-split nodes are used (bisect one edge → 2 children). 2-split and 3-split are unnecessary because recursive 1-splits achieve arbitrary granularity — each level halves the Z-span along the chosen edge. For a triangle spanning N layers, the tree reaches depth ≈ log₂(N) with ~2N leaf nodes. This is simpler to implement and sufficient for full convergence.

**DC-3: Edge Selection Strategy**
At each recursion level, the edge to split is the one whose midpoint Z is closest to the nearest unresolved layer boundary within the sub-triangle's Z-span. This greedily places splits where they most reduce the number of layer-boundary crossings per leaf.

**DC-4: Input Guard Unchanged**
The `is_sub_painted()` guard on `read_3mf()` remains as-is. Sub-painted INPUT is still rejected or flattened via `--flatten`. This spec addresses output-only sub-triangle encoding.

**DC-5: New Module Isolation**
Boundary detection and tree-building logic lives in a new `subdivision.py` module, not embedded in existing modules. This preserves separation of concerns and testability.

**DC-6: Pipeline Data Flow**
The pipeline currently produces `face_filaments: np.ndarray` (1D array of 1-based filament ints). With boundary splitting enabled, the pipeline must produce a per-face sequence of hex strings. Interior faces map directly via `filament_to_hex()`. Boundary faces get their hex string from the bisection tree encoder.

## Acceptance Criteria

- [ ] **AC-1**: `--boundary-split` flag processes a 3MF and produces output with sub-triangle hex strings on boundary faces
- [ ] **AC-2**: Without `--boundary-split`, output is byte-identical to spec 001 for the same input
- [ ] **AC-3**: Generated hex strings round-trip correctly through `encode_bisection_tree()` / `decode_bisection_tree()`
- [ ] **AC-4**: Boundary face count and percentage are reported in `--verbose` output
- [ ] **AC-5**: Output loads in PrusaSlicer without import errors (manual verification)
- [ ] **AC-6**: Output loads in BambuStudio and renders sub-painted triangles with visible boundary precision improvement (manual verification)
- [ ] **AC-7**: Output loads in OrcaSlicer without import errors (manual verification)
- [ ] **AC-8**: Well-tessellated 100k-face mesh with `--boundary-split` completes in under 15 seconds
- [ ] **AC-9**: Cube model (12 faces, full-height triangles spanning hundreds of layers) produces correct per-layer coloring — verified by decoding the bisection trees and confirming each leaf maps to the expected layer's filament
- [ ] **AC-10**: Existing `--flatten` flag continues to work for sub-painted input files
- [ ] **AC-11**: Config file `boundary_split` and `max_split_depth` fields are respected, with CLI flags taking precedence
- [ ] **AC-12**: `--max-split-depth 0` is equivalent to `--no-boundary-split` (no sub-triangle encoding)

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D-1 | Sub-triangle coloring over mesh subdivision | Zero triangle count change, no slicer performance regression, full convergence via recursive depth. See comparison table in Context. |
| D-2 | Opt-in via `--boundary-split` CLI flag | Preserves full backward compatibility. Users who don't need boundary precision get identical behavior to spec 001. |
| D-3 | Automatic convergence depth (cap 12) | Depth is not a tuning knob — it's driven by geometry. A cube face triangle spanning 200 layers needs depth ~8. The cap of 12 handles Z_span / layer_height up to 4096. |
| D-4 | 1-split node type only, recursive depth | 2-split and 3-split are unnecessary. Recursive 1-splits halve Z-span each level, reaching arbitrary granularity. Simpler algorithm, same result. |
| D-5 | Mesh subdivision (Strategy C) dropped from roadmap | Sub-triangle coloring is strictly superior for this use case. No further investment in geometry modification. |
| D-6 | New `subdivision.py` module | Keeps boundary detection and tree construction isolated from existing encoding, mesh, and palette logic. Clean test boundary. |
| D-7 | `write_3mf()` accepts hex strings, not filament ints | The writer should be format-agnostic. Hex strings are the native 3MF attribute format. The pipeline is responsible for converting filament indices to hex before calling the writer. |

## Open Questions

1. **Paint bucket interaction**: If a user later opens the output in the slicer's paint tool, do sub-triangle encodings survive user edits to other triangles? (Believed yes — slicer merges per-triangle independently — but needs verification.)
2. **Config schema versioning**: Should the config JSON include a schema version field to distinguish spec 001 vs spec 002 configs? (Low priority — fields are additive and optional.)
3. **Maximum tree size**: For extreme cases (very large coarse triangle + very fine layer height), the tree could have thousands of nodes. Are there practical limits in slicer import? (Likely no — the slicer paint brush can produce similar trees — but warrants testing with the actual slicers.)
