# Addendum: Multi-Split Bisection & Geometry Slicing Fallback

**Date**: 2026-04-03 | **Parent**: `specs/002-sub-triangle-boundary-coloring/spec.md`

---

## Summary of Changes

This addendum revises spec 002 based on empirical analysis of Bambu Studio's paint tool output and the failure of the original 1-split-only implementation to produce correct visual results. Key changes:

1. **Decision D-4 is reversed**: The subdivision algorithm now uses 2-split and 3-split node types, matching the slicer's native behavior.
2. **Decision D-5 is partially reversed**: Geometry slicing (`slice_faces_at_layers`) is retained as an opt-in fallback strategy.
3. **Default behavior changes**: Boundary splitting is enabled by default (was opt-in). Bisection is the default strategy; geometry slicing is the opt-in alternative.

---

## 1. Problem Statement

The original spec 002 implementation used only 1-split nodes (Decision D-4: "2-split and 3-split are unnecessary"). This was theoretically correct for Z-span convergence but produced incorrect visual output — a noisy "houndstooth" pattern instead of clean horizontal color bands. Multiple debugging rounds failed to resolve this.

The root cause was geometric, not algorithmic: 1-splits bisect a single edge, creating two irregularly shaped sub-triangles. When the split edge is nearly vertical (spanning Z layers), the resulting cut line is diagonal, not horizontal. Recursive diagonal cuts produce increasingly fragmented zigzag geometry that does not align with horizontal layer boundaries.

---

## 2. Evidence: Bambu Studio Reference Implementation

A Bambu Studio hand-painted cylinder (`samples/cylinder_bambu_painted.3mf`) was decoded and analyzed. The cylinder has 1440 faces (720 painted, 720 unpainted cap faces), Z range [−16.5, 16.5] (33 mm tall).

### 2.1 Split Type Usage

| Split Type | Children | Count (all trees) | Usage |
|---|---|---|---|
| 1-split | 2 | **0** | Never used |
| 2-split | 3 | 270,720 | 98.7% of all splits |
| 3-split | 4 | 3,600 | 1.3% of all splits |

Bambu Studio uses **zero 1-split nodes**. It exclusively uses 3-splits at the top levels and 2-splits throughout the remainder of the tree.

### 2.2 Tree Structure

| Metric | Value |
|---|---|
| Max tree depth | 9 (uniform across all 720 trees) |
| Total leaves (all trees) | 552,960 |
| Average leaves per face | 768 |
| Hex string lengths | 846 or 1,452 characters |
| States used | 0 (default), 2 (extruder 2) |

### 2.3 Subdivision Strategy

Bambu Studio's approach for a face with vertices at Z_top (horizontal edge) and Z_bottom:

**Phase 1 — Depth 0–1: 3-split (all edges bisected)**

A 3-split bisects all three edges at their midpoints, producing 4 child triangles. The Z-span of each child is halved. Two levels of 3-split reduce Z-span by 4×.

```
Depth 0: 33.00 mm → 3-split → 4 children at 16.50 mm each
Depth 1: 16.50 mm → 3-split → 16 sub-triangles at 8.25 mm each
```

**Phase 2 — Depth 2–8: 2-split (two edges bisected)**

A 2-split with `special_side` = the most horizontal edge (the one NOT split) bisects the two more vertical edges. Both new midpoints land at the **same Z-height**, creating a clean horizontal cut line:

```
    v0 ───────── v1       (Z_top, horizontal edge KEPT intact)
     \    upper /
      \       /
  M20 ─────── M12        (Z_mid — both midpoints at same Z!)
        \   /
   lower \ /
          v2              (Z_bottom)
```

Children:
- child[0] = (v0, v1, M12) — upper portion
- child[1] = (v0, M12, M20) — narrow strip connecting upper to lower
- child[2] = (M20, M12, v2) — lower portion

Each recursive 2-split halves the Z-span. Seven levels of 2-splits: 8.25 mm / 2⁷ = 0.064 mm, which is below the 0.1 mm layer height. Every resulting leaf sub-triangle fits within a single print layer.

### 2.4 Why 1-Split Fails

A 1-split bisects one edge at its midpoint, producing 2 children. When the split edge is vertical (spans full Z range), the midpoint is at Z_mid — but only one edge is cut. The resulting two sub-triangles are:

```
    v0 ───────── v1       (Z_top)
     \  child0 /  \
      \       / M  \      (Z_mid — midpoint of ONE edge)
       \     /      \
        \   / child1 \
         \ /          \
          v2           (Z_bottom)
```

Both children still span from Z_top to Z_bottom (one vertex remains at the extreme). The Z-span is only reduced along the split edge, not across the triangle. Recursive 1-splits create increasingly narrow diagonal slivers rather than horizontal bands. The resulting sub-triangle centroids land at unpredictable Z positions, producing the houndstooth artifact.

### 2.5 Convergence Comparison

For a 33 mm cylinder at 0.1 mm layer height (330 layers):

| Depth | Z-span (2-split) | Z-span (1-split) | Layers remaining |
|---|---|---|---|
| 0 | 33.000 mm | 33.000 mm | 330 |
| 1 | 16.500 mm | 16.500 mm | 165 |
| 2 | 8.250 mm | 8.250 mm | 82.5 |
| 3 | 4.125 mm | 4.125 mm | 41.3 |
| 4 | 2.063 mm | 2.063 mm | 20.6 |
| 5 | 1.031 mm | 1.031 mm | 10.3 |
| 6 | 0.516 mm | 0.516 mm | 5.2 |
| 7 | 0.258 mm | 0.258 mm | 2.6 |
| 8 | 0.129 mm | 0.129 mm | 1.3 |
| 9 | 0.064 mm | 0.064 mm | 0.6 ✓ |

Both converge in the same number of levels — but only 2-split produces geometrically correct horizontal band cuts. The 1-split creates the same Z-span reduction per level but along diagonal lines, causing sub-triangles to straddle multiple layers despite having narrow Z-span.

---

## 3. Revised Decisions

| # | Original Decision | Revised Decision | Rationale |
|---|---|---|---|
| D-4 | 1-split only | **2-split and 3-split required** | 1-split produces diagonal cuts, not horizontal bands. 2-split with horizontal edge kept creates exact horizontal cuts. 3-split used at top levels for efficient initial subdivision. Matches Bambu Studio behavior. |
| D-5 | Mesh subdivision dropped | **Geometry slicing retained as opt-in fallback** | Geometry slicing (`--geometry-slice`) is a working, simpler alternative. Useful for debugging or for users who prefer explicit geometry over sub-triangle encoding. |
| D-2 | Opt-in via `--boundary-split` | **Enabled by default** | Boundary splitting produces strictly better output. Users can disable with `--no-boundary-split`. |

### New Decision: D-8 — Dual Strategy with Bisection Default

The pipeline supports two boundary-handling strategies:

| Strategy | Flag | Behavior |
|---|---|---|
| **Bisection** (default) | `--boundary-split` (default on) | Encodes boundary faces as multi-split bisection trees. Zero geometry change. Slicer-native encoding. |
| **Geometry slicing** | `--geometry-slice` | Cuts mesh faces at Z-layer boundaries, creating new vertices/faces. Each sub-face spans ≤ 1 layer. Simple whole-face coloring. |
| **None** | `--no-boundary-split` | No boundary handling. Whole-triangle centroid assignment only (spec 001 behavior). |

### New Decision: D-9 — Edge Selection Strategy for 2-Split

At each recursion level, the edge selection for 2-split follows:

1. **Identify the most horizontal edge** — the edge whose two endpoints have the smallest |ΔZ|.
2. **Set `special_side`** to that edge index (the edge that is NOT split).
3. The other two edges are bisected at their midpoints.

This guarantees the two new midpoints share (approximately) the same Z-coordinate, producing a horizontal cut line. When both non-horizontal edges span a Z boundary, the cut aligns with that boundary.

### New Decision: D-10 — Split Type Selection Strategy

At each recursion level:

1. **If Z-span ≤ layer_height** (leaf): Assign the filament for the centroid's layer. No split.
2. **If all three edges have significant Z-span** (no clearly horizontal edge): Use 3-split. This occurs at the root of tall triangles where all edges span the full Z range.
3. **Otherwise**: Use 2-split with the most horizontal edge kept intact.

1-split is not used. The tree always contains 2-split and/or 3-split nodes.

---

## 4. Revised Requirements

### Modified Functional Requirements

**FR-2 (revised): Multi-Split Bisection Tree Encoding**
For each boundary face, recursively subdivide using 2-split and 3-split nodes until every leaf sub-triangle's Z-span fits within a single layer band. At each level:
- Use 3-split when no edge is clearly horizontal (all three edges have significant Z-span).
- Use 2-split with `special_side` = the most horizontal edge (smallest |ΔZ| between endpoints).
Assign each leaf the filament for the layer containing its centroid. Encode the resulting tree as a PrusaSlicer-compatible hex string.

**FR-4 (revised): Default-On Behavior**
Boundary splitting is enabled by default. A `--no-boundary-split` CLI flag disables it. When disabled, output is byte-identical to spec 001 behavior.

**FR-5 (revised): Config File Integration**
JSON config supports:
- `boundary_split: bool` (default `true`) — enable/disable boundary handling
- `max_split_depth: int` (default `12`) — safety cap on recursion depth
- `boundary_strategy: "bisection" | "geometry"` (default `"bisection"`) — select strategy

CLI flags override config values.

### New Functional Requirements

**FR-12: Geometry Slicing Strategy**
When `--geometry-slice` is specified, the pipeline slices mesh faces at Z-layer boundaries using Sutherland-Hodgman polygon clipping. Each resulting sub-face spans at most one layer and receives a simple whole-face filament assignment. This increases the output triangle count but produces geometrically exact boundaries.

**FR-13: Strategy Selection**
The `--geometry-slice` flag selects the geometry slicing strategy. Without it, bisection is used. The two strategies are mutually exclusive. `--no-boundary-split` disables both.

**FR-14: Spatial Verification**
The implementation must include a verification utility that decodes bisection trees, computes sub-triangle centroids using the actual vertex positions, and validates that each leaf's assigned filament matches the expected layer assignment. This is used in tests and available as a diagnostic tool.

### Modified Design Constraints

**DC-2 (revised): Multi-Split Node Types**
The subdivision algorithm uses 2-split (3 children) and 3-split (4 children) nodes. 1-split nodes are not emitted. The encoding/decoding codec already supports all three split types per the TriangleSelector format (see research doc Section 1.3).

**DC-3 (revised): Edge Selection Strategy**
At each recursion level, the most horizontal edge (smallest |ΔZ|) is identified and kept intact (`special_side`). The other two edges are bisected. This produces horizontal cut lines that align with layer boundaries.

---

## 5. Revised Acceptance Criteria

Additions and modifications to the original acceptance criteria:

- [ ] **AC-1 (revised)**: Boundary splitting is enabled by default and produces output with sub-triangle hex strings on boundary faces
- [ ] **AC-13**: Output from bisection strategy on the cylinder sample (`samples/cylinder.3mf`) produces clean horizontal color bands when loaded in Bambu Studio — verified by spatial analysis of decoded sub-triangle centroids (all leaves in layer N have filament matching the cyclic pattern at layer N)
- [ ] **AC-14**: Bisection trees use only 2-split and 3-split nodes (no 1-split nodes emitted)
- [ ] **AC-15**: `--geometry-slice` flag produces output with increased triangle count and correct per-face coloring
- [ ] **AC-16**: Bisection output and geometry slicing output produce equivalent visual results for the same input (both strategies assign the same filament to the same Z region)
- [ ] **AC-17**: Config field `boundary_strategy` selects between `"bisection"` and `"geometry"` modes

---

## 6. Implementation Impact

### Files to Modify

| File | Change |
|---|---|
| `subdivision.py` | Rewrite `_subdivide` / `_make_subdivider` to use 2-split and 3-split. Add edge selection by minimum |ΔZ|. Update `SplitNode` construction to use `split_sides=2` or `split_sides=3`. |
| `encoding.py` | No changes needed — codec already supports all split types. |
| `pipeline.py` | Make bisection the default path. Move geometry slicing behind `--geometry-slice` flag. Add `boundary_strategy` config field routing. |
| `config.py` | Add `boundary_strategy` field. Change `boundary_split` default to `True`. |
| `cli.py` | Add `--geometry-slice` flag. Change `--boundary-split` default to on. |
| `mesh.py` | No changes — `slice_faces_at_layers` stays for geometry strategy. |
| `test_subdivision.py` | Update tests for 2-split/3-split. Add spatial verification tests. |
| `test_encoding.py` | Add 2-split and 3-split worked examples (already partially covered). |

### Code retained from previous iteration

- `encoding.py`: `BisectionNode`, `LeafNode`, `SplitNode`, `encode_bisection_tree`, `decode_bisection_tree` — all retained, fully functional for multi-split trees.
- `mesh.py`: `slice_faces_at_layers` — retained for geometry slicing fallback.
- `subdivision.py`: `find_boundary_faces`, `encode_boundary_faces`, multiprocessing infrastructure — retained. Inner subdivision logic (`_subdivide`, `_make_subdivider`) to be rewritten.

---

## 7. Open Questions (Resolved)

| Question | Resolution |
|---|---|
| OQ-3 from original spec: Maximum tree size? | Bambu Studio produces trees with 768 leaves per face (cylinder, 330 layers). Slicer import handles this without issue. Not a practical concern. |
| Why did 1-split fail visually? | 1-split creates diagonal cut lines. Only 2-split/3-split produce horizontal cuts that align with print layers. Documented in Section 2.4 above. |
| Is mesh subdivision needed? | Retained as opt-in fallback, not the primary strategy. Bisection is preferred for zero-geometry-change output. |
