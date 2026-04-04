# PrusaSlicer TriangleSelector Bisection Tree Encoding

**Research Date**: 2026-04-03
**Status**: Complete — derived from PrusaSlicer source code analysis
**Sources**: `src/libslic3r/TriangleSelector.{cpp,hpp}`, `src/libslic3r/Model.cpp`

---

## Research Summary

**Topic**: The exact binary serialization format used by PrusaSlicer (and compatible slicers) to encode per-triangle sub-painting via recursive midpoint bisection trees, stored as hex strings in `slic3rpe:mmu_segmentation` and `paint_color` 3MF attributes.

**Relevance**: This is the authoritative specification needed to implement sub-triangle coloring in the full-spectrum-3mf tool, moving beyond the current whole-triangle-only encoding.

## Key Findings

1. **Each node is encoded as exactly one 4-bit nibble** (not 8-bit bytes). Leaf nodes with state ≥ 3 use a **two-nibble extended encoding** (prefix nibble + state nibble).
2. **Tree traversal is depth-first, children in REVERSE index order** for PrusaSlicer 2.3.1 backward compatibility.
3. **The hex string is reversed relative to the bitstream**: the rightmost hex character encodes the root node; the leftmost encodes the deepest leaf.
4. **Bits within each nibble are LSB-first** in the bitstream but are mapped to standard hex digit values during string conversion.
5. **The encoding supports up to 16 states** (0 = uncolored/default, 1–15 = extruder/filament slots), and up to 3-way edge splitting per triangle.

---

## 1. Nibble Encoding Format

Every tree node (root, interior, or leaf) is encoded as a **4-bit nibble** with the bit layout:

```
Nibble: [bit3 bit2 bit1 bit0]
         ──xx── ──yy──
```

| bits `[1:0]` (yy) | Meaning | bits `[3:2]` (xx) meaning | Children |
|----|----|----|-----|
| `00` | **Leaf** (not split) | `TriangleStateType` (0, 1, or 2) | 0 |
| `00` (with xx=`11`) | **Leaf, extended** | Sentinel → read NEXT nibble as `state - 3` | 0 |
| `01` | **Split 1 edge** | `special_side` (which edge is split) | 2 |
| `10` | **Split 2 edges** | `special_side` (which edge is NOT split) | 3 |
| `11` | **Split 3 edges** | `special_side` (always 0, ignored) | 4 |

### 1.1 Leaf Node — Simple Mode (4 bits)

For `TriangleStateType` values 0, 1, or 2 (covers: NONE, Extruder1, Extruder2):

```
Nibble = (state << 2) | 0b00
```

| State | Binary | Hex | Meaning |
|-------|--------|-----|---------|
| 0 (NONE) | `0000` | `0` | Uncolored / default extruder |
| 1 (Extruder1) | `0100` | `4` | Filament slot 1 |
| 2 (Extruder2) | `1000` | `8` | Filament slot 2 |

### 1.2 Leaf Node — Extended Mode (8 bits / 2 nibbles)

For `TriangleStateType` values 3–15 (Extruder3 through Extruder15):

```
First nibble:  0b1100 = 0xC  (sentinel: xx=11, yy=00)
Second nibble: state - 3      (value 0–12)
```

| State | Nibble 1 | Nibble 2 | Hex String | Meaning |
|-------|----------|----------|------------|---------|
| 3 | `1100` (C) | `0000` (0) | `0C` | Extruder 3 |
| 4 | `1100` (C) | `0001` (1) | `1C` | Extruder 4 |
| 5 | `1100` (C) | `0010` (2) | `2C` | Extruder 5 |
| 6 | `1100` (C) | `0011` (3) | `3C` | Extruder 6 |
| 7 | `1100` (C) | `0100` (4) | `4C` | Extruder 7 |
| 8 | `1100` (C) | `0101` (5) | `5C` | Extruder 8 |
| 9 | `1100` (C) | `0110` (6) | `6C` | Extruder 9 |
| 10 | `1100` (C) | `0111` (7) | `7C` | Extruder 10 |
| 11 | `1100` (C) | `1000` (8) | `8C` | Extruder 11 |
| 12 | `1100` (C) | `1001` (9) | `9C` | Extruder 12 |
| 13 | `1100` (C) | `1010` (A) | `AC` | Extruder 13 |
| 14 | `1100` (C) | `1011` (B) | `BC` | Extruder 14 |
| 15 | `1100` (C) | `1100` (C) | `CC` | Extruder 15 |

> **Note**: The hex string column shows the final string output (reversed bitstream order — see Section 4).

### 1.3 Interior (Split) Node (4 bits)

```
Nibble = (special_side << 2) | num_split_sides
```

| Split sides | special_side meaning | Children count |
|----|----|-----|
| 1 (`yy=01`) | Edge index that IS split (0, 1, or 2) | 2 |
| 2 (`yy=10`) | Edge index that is NOT split (kept intact) | 3 |
| 3 (`yy=11`) | Always 0 (ignored) | 4 |

Examples:

| Description | Binary | Hex |
|----|----|----|
| Split 1 edge, edge 0 split | `0001` | `1` |
| Split 1 edge, edge 1 split | `0101` | `5` |
| Split 1 edge, edge 2 split | `1001` | `9` |
| Split 2 edges, edge 0 kept | `0010` | `2` |
| Split 2 edges, edge 1 kept | `0110` | `6` |
| Split 2 edges, edge 2 kept | `1010` | `A` |
| Split 3 edges | `0011` | `3` |

---

## 2. Tree Traversal Order

### 2.1 Serialization: Depth-First, Children in Reverse Index Order

From `TriangleSelector::serialize()` (line 1826):

```cpp
// Now save all children.
// Serialized in reverse order for compatibility with PrusaSlicer 2.3.1.
for (int child_idx = split_sides; child_idx >= 0; -- child_idx)
    this->serialize(tr.children[child_idx]);
```

For a node with `split_sides = 1` (2 children): serialize child[1] first, then child[0].
For a node with `split_sides = 2` (3 children): serialize child[2], child[1], child[0].
For a node with `split_sides = 3` (4 children): serialize child[3], child[2], child[1], child[0].

### 2.2 Deserialization: Depth-First, Children Assigned in Reverse Index Order

From `TriangleSelector::deserialize()` (line 1938):

```cpp
int child_idx = last.total_children - last.processed_children - 1;
```

The first node read from the stream is assigned to `child[N-1]`, the next to `child[N-2]`, etc.

This ensures that the serialization order is correctly reversed during deserialization, maintaining consistency.

### 2.3 Traversal Consequence

The bitstream stores nodes in this order:
```
Root → child[N-1] → child[N-1]'s subtree (depth-first) → child[N-2] → ... → child[0]
```

---

## 3. Edge Split Convention

### 3.1 Edge Indices

For a triangle with vertices `v[0], v[1], v[2]`:
- **Edge 0**: `v[0] → v[1]`
- **Edge 1**: `v[1] → v[2]`
- **Edge 2**: `v[2] → v[0]`

### 3.2 Splitting Mechanics (perform_split)

When splitting, vertices are rotated so `special_side` vertex comes first, then a midpoint vertex is inserted.

**1-split (split_sides=1, special_side=s)**:
- The edge at index `s` is bisected at its midpoint `M`
- 2 child triangles are created
- `special_side` = the edge that IS split

**2-split (split_sides=2, special_side=s)**:
- Two edges are split (the ones that are NOT `s`)
- 3 child triangles are created
- `special_side` = the edge that is NOT split (kept intact)

**3-split (split_sides=3)**:
- All three edges are split at midpoints
- 4 child triangles created (the original is subdivided into 4)
- `special_side` = always 0

---

## 4. Hex String ↔ Bitstream Conversion

### 4.1 Bitstream → Hex String (`get_triangle_as_string`, Model.cpp:1604)

```cpp
while (offset < end) {
    int next_code = 0;
    for (int i=3; i>=0; --i) {
        next_code = next_code << 1;
        next_code |= int(m_data.bitstream[offset + i]);
    }
    offset += 4;
    char digit = next_code < 10 ? next_code + '0' : (next_code-10)+'A';
    out.insert(out.begin(), digit);  // ← PREPEND
}
```

**Critical detail**: Each nibble is **prepended** to the output string. This means:
- The **first** nibble in the bitstream (= the root node) becomes the **last** (rightmost) character
- The **last** nibble in the bitstream (= deepest leaf) becomes the **first** (leftmost) character

### 4.2 Hex String → Bitstream (`set_triangle_from_string`, Model.cpp:1630)

```cpp
for (auto it = str.crbegin(); it != str.crend(); ++it) {
    const char ch = *it;
    int dec = /* hex char to int */;
    for (int i = 0; i < 4; ++i)
        m_data.bitstream.insert(m_data.bitstream.end(), bool(dec & (1 << i)));
}
```

**Critical detail**: The hex string is iterated in **reverse** (last char first), and each hex digit is expanded to 4 bits **LSB-first** and appended to the bitstream.

### 4.3 Summary of String ↔ Bitstream Relationship

```
Hex string:  [leftmost char]  ...  [rightmost char]
                    ↑                       ↑
              Deepest leaf              Root node
              (last in bitstream)    (first in bitstream)
```

**The hex string reads RIGHT-TO-LEFT for tree traversal order.**

### 4.4 Bit Order Within Nibble

Bits within each nibble are stored LSB-first in the bitstream:
- `bitstream[i+0]` = bit 0 (LSB)
- `bitstream[i+1]` = bit 1
- `bitstream[i+2]` = bit 2
- `bitstream[i+3]` = bit 3 (MSB)

When converting to a hex character, standard binary→hex mapping applies:
```
nibble_value = bit0 * 1 + bit1 * 2 + bit2 * 4 + bit3 * 8
```

---

## 5. Worked Examples

### 5.1 Whole Triangle — Extruder 1

```
State = 1, not split
Nibble: (1 << 2) | 0 = 0100 = 0x4
Bitstream: [0, 0, 1, 0]
Hex string: "4"  (single char, root is rightmost = only char)
```

### 5.2 Whole Triangle — Extruder 3 (Extended)

```
State = 3, not split
Nibble 1: 0b1100 = 0xC (sentinel)
Nibble 2: 3 - 3 = 0 = 0x0
Bitstream: [0, 0, 1, 1,  0, 0, 0, 0]
            nibble1(C)   nibble2(0)

get_triangle_as_string:
  Read nibble1 → C → prepend → "C"
  Read nibble2 → 0 → prepend → "0C"
Hex string: "0C"
```

### 5.3 One Split — Two Children

Triangle split on edge 0 (`special_side=0`, `split_sides=1`).
Child 0 = Extruder1 (state=1), Child 1 = Extruder2 (state=2).

**Serialization order** (depth-first, reverse children):
1. Root: `split_sides=1, special_side=0` → nibble = `(0 << 2) | 1` = `0001` = 0x1
2. Child[1] (serialized first): state=2 → nibble = `(2 << 2) | 0` = `1000` = 0x8
3. Child[0] (serialized second): state=1 → nibble = `(1 << 2) | 0` = `0100` = 0x4

**Bitstream**: `[1,0,0,0, 0,0,0,1, 0,0,1,0]`
               (root=1)  (child1=8) (child0=4)

**Hex string construction** (prepending each digit):
```
Read 0x1 → prepend → "1"
Read 0x8 → prepend → "81"
Read 0x4 → prepend → "481"
```

**Final hex string: `"481"`**

**Verification (decode "481")**:
```
Read string in reverse: '1', '8', '4'
  '1' → bitstream: [1,0,0,0]
  '8' → bitstream: [1,0,0,0, 0,0,0,1]
  '4' → bitstream: [1,0,0,0, 0,0,0,1, 0,0,1,0]

Deserialize:
  next_nibble() → 1: split_sides=1, special_side=0 → split, 2 children
  next_nibble() → 8: split_sides=0, state=8>>2=2 → leaf, Extruder2 → assign to child[1]
  next_nibble() → 4: split_sides=0, state=4>>2=1 → leaf, Extruder1 → assign to child[0]
✓ Correct!
```

### 5.4 Three-Way Split (All Edges)

Triangle split on all 3 edges (`split_sides=3`, `special_side=0`).
Children: child[0]=Ext1, child[1]=Ext2, child[2]=Ext1, child[3]=Ext2.

**Serialization** (reverse: child3, child2, child1, child0):
1. Root: `(0 << 2) | 3` = `0011` = 0x3
2. Child[3]: state=2 → `1000` = 0x8
3. Child[2]: state=1 → `0100` = 0x4
4. Child[1]: state=2 → `1000` = 0x8
5. Child[0]: state=1 → `0100` = 0x4

**Bitstream**: root(3), c3(8), c2(4), c1(8), c0(4)

**Hex string**: prepending → `"48483"` (read each nibble, prepend)
```
"3" → "83" → "483" → "8483" → "48483"
```

### 5.5 Nested Split (Two Levels Deep)

Root split on edge 0 (split_sides=1, special_side=0).
Child[0] = Extruder1 (leaf).
Child[1] = split on edge 1 (split_sides=1, special_side=1), with:
  - grandchild[0] = Extruder1
  - grandchild[1] = Extruder2

**Serialization** (depth-first, reverse children):
1. Root: `(0<<2)|1` = 0x1
2. Child[1] (first, because reverse): `(1<<2)|1` = `0101` = 0x5 (split node)
3.   Grandchild[1] of child[1]: state=2 → 0x8
4.   Grandchild[0] of child[1]: state=1 → 0x4
5. Child[0] (second): state=1 → 0x4

**Bitstream**: 1, 5, 8, 4, 4

**Hex string**: `"44851"`
```
"1" → "51" → "851" → "4851" → "44851"
```

---

## 6. TriangleStateType Enum

From `TriangleSelector.hpp` (line 32):

```cpp
enum class TriangleStateType : int8_t {
    NONE      = 0,   // Default extruder (uncolored)
    ENFORCER  = 1,   // Also: Extruder1, FUZZY_SKIN
    BLOCKER   = 2,   // Also: Extruder2
    Extruder3 = 3,
    Extruder4,       // = 4
    Extruder5,       // = 5
    // ... through ...
    Extruder15 = 15,
    Count      = 16
};
```

**Important**: `NONE` (0) means the triangle uses the object's default extruder. It is NOT the same as "no painting" — unpainted triangles are simply omitted from the data entirely (empty hex string). State 0 explicitly encodes "use default."

The maximum number of distinct extruder states is **16** (0 through 15), providing support for up to **15 extruders** plus the default.

---

## 7. Data Storage in 3MF

### 7.1 Internal Representation (`TriangleSplittingData`)

```cpp
struct TriangleSplittingData {
    std::vector<TriangleBitStreamMapping> triangles_to_split;  // (triangle_idx, bitstream_offset)
    std::vector<bool> bitstream;                                // all nibbles concatenated
    std::vector<bool> used_states;                              // which states are present
};
```

Only triangles that are painted (state ≠ NONE) or split are stored. Unpainted triangles are omitted entirely.

### 7.2 3MF XML Attribute

Per-triangle hex strings are stored as semicolon-delimited attribute values on `<triangle>` elements:

**PrusaSlicer namespace** (`slic3rpe:mmu_segmentation`):
```xml
<triangle v1="0" v2="1" v3="2" slic3rpe:mmu_segmentation="481" />
```

**BambuStudio/OrcaSlicer** (`paint_color`):
```xml
<triangle v1="0" v2="1" v3="2" paint_color="481" />
```

Empty string or absent attribute = unpainted (default extruder).

---

## 8. Compatibility: PrusaSlicer vs OrcaSlicer vs BambuStudio

### 8.1 Encoding Format

All three slicers use **the same TriangleSelector encoding format**. This is confirmed by:
- OrcaSlicer is a fork of BambuStudio, which forked from PrusaSlicer
- The Blender 3MF addon issue (#8) confirms OrcaSlicer "already can import these color zones"
- The `TriangleSelector` class is shared code across all forks

### 8.2 Attribute Names

| Slicer | Attribute Name | Namespace |
|--------|---------------|-----------|
| PrusaSlicer | `slic3rpe:mmu_segmentation` | `http://schemas.slic3r.org/3mf/2017/06` |
| BambuStudio | `paint_color` | default (no namespace prefix) |
| OrcaSlicer | `paint_color` | default (no namespace prefix) |

### 8.3 Known Differences

- **Attribute name**: PrusaSlicer uses `slic3rpe:mmu_segmentation`; Bambu/Orca use `paint_color`
- **Color metadata**: PrusaSlicer stores extruder colors in `Metadata/Slic3r_PE.config` (`extruder_colour`); BambuStudio stores them differently
- **Encoding**: Binary format is identical across all three

### 8.4 Extruder Limit Per Slicer

From `GLGizmoMmuSegmentation.hpp` (line 99):
```cpp
// TriangleSelector::serialization/deserialization has a limit to store 19 different states.
// EXTRUDER_LIMIT + 1 states are used to storing the painting because also uncolored
// triangles are stored.
```

The encoding supports 16 states (0–15). In practice, PrusaSlicer MMU supports 5 extruders (MMU2S) or more with XL. BambuStudio supports up to 16 AMS slots.

---

## 9. Code References

| Component | File | Key Functions |
|-----------|------|---------------|
| Serialization | `src/libslic3r/TriangleSelector.cpp:1789-1862` | `TriangleSelector::serialize()` |
| Deserialization | `src/libslic3r/TriangleSelector.cpp:1872-1968` | `TriangleSelector::deserialize()` |
| Hex→Bitstream | `src/libslic3r/Model.cpp:1630-1657` | `FacetsAnnotation::set_triangle_from_string()` |
| Bitstream→Hex | `src/libslic3r/Model.cpp:1604-1624` | `FacetsAnnotation::get_triangle_as_string()` |
| State enum | `src/libslic3r/TriangleSelector.hpp:32-59` | `enum class TriangleStateType` |
| Triangle class | `src/libslic3r/TriangleSelector.hpp:420-474` | `TriangleSelector::Triangle` |
| Split logic | `src/libslic3r/TriangleSelector.cpp:1455-1526` | `TriangleSelector::perform_split()` |
| Data structures | `src/libslic3r/TriangleSelector.hpp:267-313` | `TriangleBitStreamMapping`, `TriangleSplittingData` |
| MMU Gizmo | `src/slic3r/GUI/Gizmos/GLGizmoMmuSegmentation.hpp` | UI + rendering |
| State update | `src/libslic3r/TriangleSelector.cpp:1972-2002` | `update_used_states()` |
| Has facets | `src/libslic3r/TriangleSelector.cpp:2006-2070` | `has_facets()` (lightweight decode) |

---

## 10. Gotchas and Edge Cases

### 10.1 The Hex String is Reversed

The rightmost character is the root. Tools that process the hex string left-to-right will read leaves first and the root last. This is **contrary to intuition** and the most common source of bugs.

### 10.2 Cannot Blindly Remap Extruder Bits

A recent PrusaSlicer issue (#7314, kurtgluck comment) documents a bug where remapping extruder bits caused "the shape of the colored region changes around its edges." This happens because:

- **Split nodes** use bits `[3:2]` for `special_side` (geometry), NOT extruder state
- Only **leaf nodes** (bits `[1:0]` = `00`) have extruder state in bits `[3:2]`
- You must parse the tree structure to identify leaves before remapping

### 10.3 State 0 vs Empty String

- **Empty string** = triangle is not in the data at all → uses object default extruder
- **State 0 (`"0"`)** = triangle IS in the data, explicitly set to default → semantically the same but stored differently
- During serialization, `TriangleStateType::NONE` triangles that aren't split are skipped entirely

### 10.4 Extended Encoding Sentinel

The value `0b11` in bits `[3:2]` with `0b00` in bits `[1:0]` (nibble = `0xC`) is a **sentinel**, not a state. If you see nibble `0xC` for a leaf, you MUST read the next nibble to get the actual state. Treating `0xC` as state 3 is incorrect.

### 10.5 Children Count

| `split_sides` (bits [1:0]) | Children | Total nibbles for subtree |
|-----|-----|-----|
| 0 | 0 (leaf) | 1 (or 2 if extended) |
| 1 | 2 | 1 + recursive |
| 2 | 3 | 1 + recursive |
| 3 | 4 | 1 + recursive |

### 10.6 Backward Compatibility

The reverse child order was chosen explicitly for PrusaSlicer 2.3.1 compatibility. The extended 2-nibble state encoding was added later for MMU support (states 3+). Files created with older PrusaSlicer versions only use states 0–2 (simple 4-bit encoding).

### 10.7 No Padding

The bitstream has no padding. The hex string length is always `ceil(bitstream_length / 4)` and every nibble is meaningful. There is no length prefix or terminator.

---

## 11. Algorithm: Decoding a Hex String

```python
def decode_triangle(hex_str: str) -> dict:
    """Decode an mmu_segmentation/paint_color hex string into a tree."""
    if not hex_str:
        return {"type": "default"}

    # Step 1: Convert hex string to nibble list (reversed)
    nibbles = []
    for ch in reversed(hex_str):
        nibbles.append(int(ch, 16))

    pos = 0

    def read_nibble():
        nonlocal pos
        n = nibbles[pos]
        pos += 1
        return n

    def decode_node():
        code = read_nibble()
        split_sides = code & 0b11

        if split_sides == 0:
            # Leaf node
            state_bits = (code >> 2) & 0b11
            if state_bits == 0b11:
                # Extended: read next nibble for state
                state = read_nibble() + 3
            else:
                state = code >> 2
            return {"type": "leaf", "state": state}
        else:
            # Interior (split) node
            special_side = code >> 2
            num_children = split_sides + 1
            # Children are in reverse order in the stream
            children_reversed = [decode_node() for _ in range(num_children)]
            children = list(reversed(children_reversed))
            return {
                "type": "split",
                "split_sides": split_sides,
                "special_side": special_side,
                "children": children,
            }

    return decode_node()
```

## 12. Algorithm: Encoding a Tree to Hex String

```python
def encode_triangle(node: dict) -> str:
    """Encode a tree into an mmu_segmentation/paint_color hex string."""
    bits = []  # bitstream, LSB-first nibbles

    def push_nibble(value: int):
        for i in range(4):
            bits.append((value >> i) & 1)

    def encode_node(n):
        if n["type"] == "leaf":
            state = n["state"]
            if state < 3:
                push_nibble((state << 2) | 0b00)
            else:
                push_nibble(0b1100)  # sentinel
                push_nibble(state - 3)
        elif n["type"] == "split":
            split_sides = n["split_sides"]
            special_side = n["special_side"]
            push_nibble((special_side << 2) | split_sides)
            # Serialize children in REVERSE index order
            for child in reversed(n["children"]):
                encode_node(child)

    encode_node(node)

    # Convert bitstream to hex string (prepending each digit)
    hex_chars = []
    for i in range(0, len(bits), 4):
        value = sum(bits[i + j] << j for j in range(4))
        hex_chars.insert(0, format(value, 'X'))

    return ''.join(hex_chars)
```

---

## Open Questions

- **T-joint handling**: When deserializing for rendering, PrusaSlicer handles T-joints at boundaries between split and unsplit neighbor triangles via `get_facets_strict_recursive` / `get_facets_split_by_tjoints`. This is a rendering concern, not a serialization concern.
- **Midpoint vertex sharing**: Adjacent triangles sharing a split edge reuse the same midpoint vertex. This matters for mesh reconstruction but not for encoding/decoding the hex string.
- **Maximum tree depth**: Not explicitly limited in the code, but constrained by the `edge_limit` parameter (brush diameter). Typical real-world depth is 5–10 levels.

---

## References

| Source | Type | Date | Notes |
|--------|------|------|-------|
| `prusa3d/PrusaSlicer` `src/libslic3r/TriangleSelector.cpp` | Source code | Current main branch | Authoritative serialize/deserialize implementation |
| `prusa3d/PrusaSlicer` `src/libslic3r/Model.cpp` | Source code | Current main branch | Hex string ↔ bitstream conversion |
| [PrusaSlicer #7314](https://github.com/prusa3d/PrusaSlicer/issues/7314) | GitHub issue | 2021-11 | hejllukas (PrusaSlicer dev) explains encoding architecture |
| [Blender 3MF Addon #8](https://github.com/Clonephaze/3MF-Blender-Add-on---Maintained/issues/8) | GitHub issue | 2025-02 | Community reverse-engineering + working Blender import/export |
| [amoose136 SegmentationString tool](https://www.amoose.org/SegmentationString) | Web tool | 2025-02 | Browser-based hex string decoder/visualizer |
| [kurtgluck Printables article](https://www.printables.com/article/3mf-file-color-specification-what-i-have-found-v4-YNYjaE5) | Blog | 2026-03 | Documents gotcha with extruder bit remapping |
