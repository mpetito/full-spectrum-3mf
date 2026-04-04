# Status: Sub-Triangle Boundary Coloring — Sawtooth Investigation

**Date**: 2026-04-04 | **Parent**: `specs/002-sub-triangle-boundary-coloring/spec.md`

---

## 1. Current State

The bisection tree encoder is functional and produces output that loads in Bambu Studio. Key milestones completed:

| Milestone | Status |
|---|---|
| `layer_filament_map` construction | ✅ Fixed |
| Parallel processing optimized (~3.5s pipeline) | ✅ |
| Bambu `special_side` convention for all split types | ✅ Fixed |
| 2-split child ordering (c0=apex, c1=middle, c2=base) | ✅ Fixed |
| 3-split c2 vertex ordering `(m12, v2, m20)` | ✅ Fixed |
| No 1-split nodes emitted (AC-14) | ✅ |
| Output uniform across cylinder height | ✅ |
| All 267 tests pass | ✅ |
| **Clean horizontal band edges** | ❌ **Sawtooth artifact remains** |

Visual output shows alternating color bands at the correct Z-heights, but many band **edges have a sawtooth/serrated pattern** instead of clean horizontal lines.

---

## 2. Root Cause Analysis

### 2.1 The Immediate Problem: Binary Cut–Layer Misalignment

At max depth 9, the subdivision produces cuts at Z-values that are binary fractions of the original triangle's Z-span:

```
Z-resolution at depth 9 = 33mm / 2⁹ = 33/512 ≈ 0.0644mm
Layer boundaries at 0.1mm intervals
```

These do NOT align. Analysis of the cylinder (330 layers):

| Metric | Value |
|---|---|
| Layer boundaries with misalignment > 0.01mm | **228 / 329 (69%)** |
| Layer boundaries with misalignment > 0.03mm | 24 / 329 (7%) |
| Maximum misalignment | 0.032mm |
| Leaves straddling layer boundaries | **9,858 / 15,055 (65%)** |

When a leaf sub-triangle straddles a layer boundary, its color is determined by centroid position. Different triangle shapes (from different parent split paths) produce centroids on opposite sides of the boundary → inconsistent coloring → sawtooth.

### 2.2 The Deeper Problem: Missing 3-Splits

**This is the primary root cause.** The current edge selection uses Z-span squared (`dz²`) to classify edges as "long" or "short". On the cylinder:

- Horizontal edge: `|ΔZ| = 0` → **never classified as "long"**
- Vertical edges: `|ΔZ| = 33mm` → always "long"
- Result: `n_long ≤ 2` → **3-split is never triggered**

Bambu Studio uses **3D squared edge length** for classification:

- Horizontal edge: `3D length ≈ 0.288mm`, `sq = 0.083 > 0.01` → **classified as "long"**
- Vertical edges: `3D length ≈ 33mm` → long
- Result: `n_long = 3` → **3-split at root**

#### Comparison: Our output vs Bambu reference (single face)

| Metric | Our Output | Bambu Reference |
|---|---|---|
| Hex string length | **22,582 chars** | 846 chars |
| 3-split nodes | **0** | 5 |
| 2-split nodes | **7,527** | 275 |
| Leaf nodes | **15,055** | 566 |
| Tree ratio | **27× larger** | baseline |
| Root split type | 2-split | 3-split |

The 3-splits at the top levels are critical because they reduce ALL edge dimensions simultaneously, including the horizontal edge. Without them, each 2-split only bisects 2 of the 3 edges; the "middle" child (c1) still spans the full Z-range of its parent's non-kept edges, requiring many more levels to converge.

### 2.3 Why 3-Split Matters: Convergence Rate

With 3-split at the top levels, Bambu's tree achieves:

```
Depth 0: 3-split → 4 children, horizontal edge halved
Depth 1: 3-split → 16 sub-triangles, horizontal edge quartered (0.072mm < 0.1mm threshold)
Depth 2+: 2-split → horizontal edge is now "short" in 3D, kept intact → clean horizontal cuts
```

Without 3-split (our approach), every level produces 3 children (2-split), and the "middle" child c1 always needs further splitting because it SPANS the same Z-range as the non-kept edges of its parent:

```
Depth 0: 2-split → 3 children, c1 still spans full Z-range
Depth 1: 2-split on c1 → 3 more children, c1.c1 still spans half Z-range
...continues for 9 levels → massive tree
```

### 2.4 Why Z-Span Was Tried (and Why It Was Partially Correct)

The Z-span approach was introduced to fix "fuzziness" caused by 3D-length edge selection in 2-split mode. With 3D length, the 2-split sometimes kept a non-horizontal edge (one that was shorter in 3D but had non-zero Z-span), producing diagonal cuts instead of horizontal ones.

**Z-span IS correct for 2-split edge selection** — it ensures horizontal cuts. But Z-span is **incorrect for the split-TYPE decision** (3-split vs 2-split) because it prevents 3-splits from ever firing.

---

## 3. Proposed Fix: Hybrid Edge Classification

Use **3D edge length for the split-type decision** (determines 3-split vs 2-split vs leaf) but **Z-span for edge selection within 2-split** (determines which edge to keep):

```
For each edge:
  3D_long[i] = (3D_length_sq[i] > limit_sq)     # for split-type decision
  dz_sq[i]   = (z_endpoint2 - z_endpoint1)²      # for edge selection

n_long = sum(3D_long)

if n_long == 3:  → 3-split (all edges bisected)
if n_long >= 1:  → 2-split, keep edge with smallest dz_sq (most horizontal)
if n_long == 0:  → leaf (centroid assignment)
```

Expected outcome:
- Root: 3-split (all edges "long" in 3D) → matches Bambu
- Depth 1: 3-split (horizontal sub-edge still 0.144mm > 0.1mm threshold) → matches Bambu
- Depth 2+: 2-split, horizontal sub-edge < threshold, other edges still "long" → kept horizontal → clean cuts
- Tree size: ~846 chars (matching Bambu) instead of 22,582 chars
- Leaf straddling: dramatically reduced (smaller triangles at boundaries)

---

## 4. Findings Summary: Bug Timeline

| # | Bug | Fix Applied | Result |
|---|---|---|---|
| 1 | `layer_filament_map` not built for auto layers | Construct from cyclic pattern | Correct layer→filament mapping |
| 2 | Performance: 60s for 720 faces | Parallel chunks, optimized fast path | ~3.5s |
| 3 | `special_side` values wrong for split types | Map our edge→Bambu side convention | Correct split nibble encoding |
| 4 | 2-split child ordering wrong | c0=apex, c1=middle, c2=base | Matches Bambu's `perform_split()` |
| 5 | 3-split c2 vertex ordering wrong | `(m12, v2, m20)` not `(m20, m12, v2)` | Correct vertex labeling for recursion |
| 6 | 3D edge length → fuzz at band edges | Switch to Z-span for edge selection | Horizontal cuts (but no 3-splits) |
| **7** | **Z-span for split-TYPE → no 3-splits → 27× tree size → sawtooth** | **Not yet applied** | **Pending: hybrid 3D/Z-span approach** |

---

## 5. Additional Observations

### 5.1 Bambu Reference Tree Structure

The Bambu reference cylinder (`samples/cylinder_bambu_painted.3mf`) was decoded:

- 720 painted faces, each with a bisection tree
- Per-face: 5 3-splits (depths 0–1), 275 2-splits (depths 2–8), 566 leaves
- Hex string lengths: 846 or 1,452 characters
- **Zero 1-split nodes** (confirms AC-14 is correct design)
- States used: 0 (default/filament 1) and 2 (filament 3 → extruder 2)
- Max depth: 9

### 5.2 Cylinder Geometry Properties

All 720 boundary faces on the cylinder have identical Z topology:

- Two vertices at Z = ±16.5 (one extreme), one vertex at the other extreme
- 360 faces are "2-top-1-bottom", 360 are "1-top-2-bottom"
- Only 2 unique Z-values exist across all vertices
- The horizontal edge (dz=0) has 3D length ≈ 0.288mm
- Vertical edges have 3D length ≈ 33mm

### 5.3 3D Edge Length at Successive Depths

For the cylinder's horizontal edge:

| Depth | 3D Length (mm) | 3D Length² | > limit_sq (0.01)? |
|---|---|---|---|
| 0 | 0.2880 | 0.0829 | ✅ long (→ 3-split) |
| 1 | 0.1440 | 0.0207 | ✅ long (→ 3-split) |
| 2 | 0.0720 | 0.0052 | ❌ short (→ 2-split) |

This matches Bambu's 5 3-splits: 1 at depth 0 + 4 at depth 1 = 5 total.

---

## 6. Open Items

### 6.1 Implementation

- [ ] Implement hybrid classification (3D length for split-type, Z-span for edge selection)
- [ ] Apply to both tree path (`_subdivide`) and fast path (`_make_subdivider`)
- [ ] Verify tree size matches Bambu reference (~846 chars per face)
- [ ] Verify visual output produces clean horizontal bands
- [ ] Update tests for 3-split triggering behavior

### 6.2 Conformance Verification

- [ ] Decode Bambu reference trees and compare child vertex ordering against our implementation
- [ ] Verify our 2-split child geometry (c0 apex, c1 middle, c2 base vertices) matches Bambu's `perform_split()` at every depth level, not just root
- [ ] Trace one full face tree (our output vs Bambu reference) nibble-by-nibble

### 6.3 Testing (E2E)

- [ ] Build end-to-end test that decodes output, reconstructs sub-triangle geometry, and verifies all leaf centroids land in the correct layer
- [ ] Build visual validation: render sub-triangle colors to an image and compare against reference
- [ ] Define "correctness metric": what % of leaf area is in the correct color band?
- [ ] Consider diff-based testing: compare our hex output vs Bambu reference per face
- [ ] Make `write_3mf()` produce BBL-compatible output so BambuStudio can slice it (see §7)
- [ ] Enable spec 003 full-pipeline tests (F5/F6/F7) once BBL-compatible output works

### 6.4 Potential Secondary Issues

Even after fixing the 3-split triggering, additional issues may surface:

1. **2-split child vertex ordering**: Our `c1 = (m20, v0, m12)` vs Bambu's ordering — needs conformance check at all depth levels
2. **3-split at depth 1**: The 4 children of the root 3-split produce sub-triangles where the horizontal edge is still "long" in 3D. The n_long for each child needs to be checked against Bambu's classification.
3. **Collapse optimization**: When all children are identical leaves, we collapse to a single leaf. Does Bambu do the same? If not, the hex strings won't match exactly.
4. **Edge limit value**: Bambu's `m_edge_limit_sqr` may differ from `layer_height²`. The reference implementation may use a different threshold.

---

## 7. BBL Compatibility Constraints

BambuStudio CLI requires **self-contained BBL 3MF files** to slice correctly. Our `write_3mf()` output currently lacks the metadata and structure BambuStudio expects, which blocks the full-pipeline E2E tests (spec 003 F5/F6/F7).

### 7.1 What BambuStudio Requires

A sliceable BBL 3MF must contain:

| Element | Purpose | Our output |
|---|---|---|
| `<metadata name="Application">BambuStudio-XX.XX.XX.XX</metadata>` | Triggers `is_bbl_3mf` flag; enables MMU segmentation parsing | ❌ Missing |
| `Metadata/project_settings.config` | Machine, process, and filament settings | ❌ Missing |
| `Metadata/model_settings.config` | Plate metadata incl. `filament_maps` | ❌ Missing |
| `Metadata/plate_N.config` | Per-plate overrides | ❌ Missing |
| `mmu_segmentation_facets` attribute (per volume) | Bisection tree paint data | ✅ Present (as `paint_color`) |
| `filament_diameter.size() > 1` in config | Triggers multi-material slicing | ❌ Only 1 filament declared |

Without the BBL metadata, BambuStudio crashes with access violation (0xC0000005) — it cannot create plate triangles.

### 7.2 What Works Today

A **smoke test** validates the slicer infrastructure end-to-end using pre-built BBL fixture 3MFs:

- `tests/fixtures/cube-10-10-4-0.1-dual-color.3mf` — hand-painted in BambuStudio 02.05.00.66, alternating filaments 1 & 2
- BambuStudio CLI slices it → produces 39 layers with perfect alternating T0/T1
- G-code parser correctly extracts per-layer tool assignments
- `pytest -m slicer` with `BAMBUSTUDIO_BIN` set → 3 tests pass

This confirms the slicer invocation, G-code extraction, and parser are all correct.

### 7.3 What's Needed for Full Pipeline Tests

To run spec 003 F5/F6/F7 (full-spectrum CLI → slicer → G-code validation), `write_3mf()` must produce BBL-compatible output. This requires:

1. **BBL application tag** — embed `<metadata name="Application">` with a BambuStudio version string
2. **Embedded project settings** — generate `project_settings.config` with machine, process, and filament definitions (at least 2 filaments for multi-material)
3. **Plate metadata** — generate `model_settings.config` with `filament_maps` and plate config
4. **Multi-filament declaration** — ensure `filament_diameter` has entries for all filaments used in paint data

These changes are part of spec 002 scope since they directly affect whether the coloring output is usable by BambuStudio.

### 7.4 OrcaSlicer Compatibility Note

OrcaSlicer 2.3.2 rejects BambuStudio 2.5 3MF files with "Version Check: File Version 2.5.0.66 not supported" (exit -24). This means:

- OrcaSlicer cannot slice the user-provided fixture 3MFs
- OrcaSlicer may be able to slice our `write_3mf()` output (non-BBL format) if given external profiles via `--load-settings` / `--load-filaments`
- The env var `ORCASLICER_BIN` is supported as a fallback but untested with current fixtures

---

## 8. Files Modified (This Session)

| File | Change |
|---|---|
| `src/full_spectrum/subdivision.py` | Replaced 3D edge length with Z-span squared for edge classification; merged n_long==1 into n_long>=1 block; eliminated 1-split code path |
| `tests/unit/test_subdivision.py` | Updated spatial verification to use correct Bambu convention vertex ordering for 2-split children |

---

## 8. Diagnostic Scripts Created

| File | Purpose |
|---|---|
| `samples/_analyze_sawtooth.py` | Leaf-level Z-span analysis, straddling leaf count and depth distribution |
| `samples/_analyze_sawtooth2.py` | Face type classification, binary cut vs layer boundary alignment analysis |
| `samples/_compare_bambu.py` | Per-face tree structure comparison between our output and Bambu reference |
