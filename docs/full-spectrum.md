# Full Spectrum 3D Printing: Slicer-Agnostic Layer Stratification CLI Tool

## Overview

The Full Spectrum technique exploits a perceptual phenomenon: when an FDM printer alternates filament colors at very low layer heights (0.08–0.12 mm), the human visual system blends the colors in a way analogous to how a CRT screen blends phosphor dots or how ink halftoning works in print. The result is a much larger perceived color gamut from a fixed set of 3–4 filaments — reportedly 10+ distinct colors from just 4 loaded spools. The community tool that pioneered this approach, `ratdoux/OrcaSlicer-FullSpectrum`, is a fork of Snapmaker OrcaSlicer and is tightly coupled to that printer's workflow. The goal of this document is to design a slicer-agnostic CLI that achieves the same result by pre-processing a model's per-triangle color assignments directly in the 3MF file before it enters any slicer.[^1][^2][^3][^4]

***

## The Technique: How Layer Dithering Works

At its core, Full Spectrum is **1D ordered dithering on the Z axis**. Instead of dithering pixels in a 2D image, it dithers print layers in the vertical direction. The printer's eye-brain integration — looking at a surface from a distance — blends the alternating layers optically, just as a TV blends RGB sub-pixels.[^3]

The phenomenon was first accidentally observed in purge towers where two filaments intermingle and produce an apparent third color. `ratdoux` formalized it into an intentional workflow using virtual filament definitions in the slicer UI.[^5][^6]

### Physical Constraints

- **Best results on vertical or near-vertical surfaces**: the Z-axis dithering produces the intended blend only when the viewer sees stacked layers from the side. Flat top/bottom surfaces show the stair-step pattern directly and look odd.[^7]
- **Transparent filaments blend better**: opaque filaments produce more visible banding between layers; lower Transmission Distance (TD) filaments show better blending. CMYK-style setups with transparent cyan, magenta, and yellow perform particularly well.[^8][^5]
- **Layer height matters**: 0.08 mm is a community-recommended sweet spot — low enough for strong blending, high enough to avoid excessive print time and filament swaps.[^6]
- **Tool-changer printers are ideal**: The Snapmaker U1, H2C, and Flashforge Creator 5 avoid purge waste entirely by swapping nozzles rather than flushing. AMS-style systems also work but generate purge waste at each color transition.[^7]

***

## 3MF File Format: Deep Dive

### Container Structure

A `.3mf` file is a renamed ZIP archive. The relevant files inside are:[^9]

```
[Content_Types].xml          # MIME type declarations (required)
_rels/.rels                  # Relationship manifest (required)
3D/3dmodel.model             # Primary XML: mesh geometry + per-triangle color
Metadata/Slic3r_PE_model.config   # Slicer-specific: default extruder per object
```

### `3D/3dmodel.model` — Mesh Geometry and Triangle Colors

This file is standard XML conforming to the 3MF Core Specification. It lists vertices and faces (triangles), with optional per-triangle color attributes:[^10]

```xml
<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US"
  xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
  xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06">
  <resources>
    <object id="1" type="model">
      <mesh>
        <vertices>
          <vertex x="18" y="18" z="-18"/>
          ...
        </vertices>
        <triangles>
          <triangle v1="0" v2="1" v3="2"/>                              <!-- default extruder -->
          <triangle v1="0" v2="4" v3="7" slic3rpe:mmu_segmentation="8"/> <!-- extruder 2 -->
          <triangle v1="2" v2="6" v3="5" slic3rpe:mmu_segmentation="0C"/> <!-- extruder 3 -->
        </triangles>
      </mesh>
    </object>
  </resources>
  <build>
    <item objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 0" printable="1"/>
  </build>
</model>
```

Triangles without a color attribute inherit the default extruder from `Slic3r_PE_model.config`.[^9]

### The Extruder Encoding (Critical Detail)

Extruder indices in `mmu_segmentation` (PrusaSlicer) and `paint_color` (BambuStudio/OrcaSlicer) are **not** stored as plain integers. They use a bit-packed hexadecimal encoding:[^11][^9]

| Extruder | Hex Code | Binary Notes |
|----------|----------|--------------|
| 1 | `4` | `0100`: high bits = `01` (extruder 1), low bits = `00` (no split) |
| 2 | `8` | `1000`: high bits = `10` (extruder 2), low bits = `00` |
| 3 | `0C` | 8-bit: `00001100` |
| 4 | `1C` | 8-bit: `00011100` |
| 5 | `2C` | 8-bit: `00101100` |
| 6 | `3C` | 8-bit: `00111100` |

The **two least-significant bits** encode triangle subdivision state (whether the triangle has been painted across sub-regions). For whole-triangle coloring — which is all that the CLI tool needs — these bits are always `00`, and the simple table above applies directly.[^9]

For triangles that have been **sub-painted** (e.g., a circle painted on a face in the slicer), the `mmu_segmentation` value becomes a long multi-byte string encoding a recursive bisection tree. This complex encoding is slicer-internal and should not be generated by this tool. When the tool encounters a pre-painted input with sub-triangle entries, it should either reject them or flatten them to the dominant extruder of that triangle.

### Namespace Difference: PrusaSlicer vs. BambuStudio/OrcaSlicer

Both ecosystems use the same bit encoding but different XML attribute names:[^12]

- **PrusaSlicer / Snapmaker OrcaSlicer**: `slic3rpe:mmu_segmentation="8"`
- **BambuStudio / upstream OrcaSlicer**: `paint_color="8"`

A robust implementation should read both on input and write both (or allow the user to select target format). The namespace declaration `xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06"` must be present on the root `<model>` element when using the slic3rpe attribute.

### `Metadata/Slic3r_PE_model.config`

This file assigns the default extruder for the whole object. It is a separate XML file within the ZIP:

```xml
<?xml version="1.0" encoding="UTF-8"?>
g>
  <object id="1">
    <metadata type="object" key="extruder" value="1"/>
  </object>
</config>
```

For the layer-stratification use case, the default extruder in this file will correspond to the "extruder 1" slot, with all per-layer colors encoded as triangle attributes.

***

## Core Algorithm: Layer Stratification

### Step 1: Load the Input Mesh

**Library**: `trimesh` (pure Python, pip-installable)[^13]

```python
import trimesh
mesh = trimesh.load("input.stl")  # or .3mf, .obj
```

For 3MF inputs with pre-existing color annotations, the XML must be read separately from the geometry (trimesh does not currently expose `mmu_segmentation`/`paint_color` as a first-class feature for FDM slicer annotations). The recommended approach is to load geometry via trimesh and parse color attributes via `xml.etree.ElementTree` or `lxml` against the unpacked `3dmodel.model` file directly.

### Step 2: Parse Per-Triangle Input Colors

Unpack the 3MF (it is a ZIP) and parse `3D/3dmodel.model`:

```python
import zipfile, xml.etree.ElementTree as ET

with zipfile.ZipFile("input.3mf", "r") as zf:
    model_xml = zf.read("3D/3dmodel.model")

tree = ET.fromstring(model_xml)
ns = {
    "m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02",
    "slic3rpe": "http://schemas.slic3r.org/3mf/2017/06"
}
# Build face_to_extruder dict: face_index -> int extruder (1-based)
# Triangles without attribute get extruder 1 (default)
```

The hex-to-extruder decode function (for whole-triangle cases only):

```python
def decode_extruder(hex_str: str) -> int:
    """Decode slic3rpe:mmu_segmentation or paint_color to 1-based extruder index."""
    if len(hex_str) <= 2:
        val = int(hex_str, 16)
        high = (val >> 2)  # high 6 bits are extruder encoding
        if high == 1: return 1
        if high == 2: return 2
        # For 2-nibble codes, check known table
    TABLE = {"4": 1, "8": 2, "0C": 3, "1C": 4, "2C": 5, "3C": 6,
             "4C": 7, "5C": 8, "6C": 9, "7C": 10}
    return TABLE.get(hex_str.upper(), 1)

def encode_extruder(extruder_1based: int) -> str:
    RTABLE = {1: "4", 2: "8", 3: "0C", 4: "1C", 5: "2C", 6: "3C",
              7: "4C", 8: "5C", 9: "6C", 10: "7C"}
    return RTABLE.get(extruder_1based, "4")
```

### Step 3: Split Faces at Z-Layer Boundaries (Optional, for Precision)

Faces that **cross** a Z-layer boundary will have their centroid in one layer but part of their area in an adjacent layer. For most models with many faces, this is a small minority and the centroid-based assignment produces acceptable results. However, for clean results the mesh can be subdivided at every Z plane:

```python
import numpy as np
from trimesh.intersections import slice_faces_plane

z_min, z_max = mesh.bounds[:, 2]
layer_planes = np.arange(z_min + layer_height, z_max, layer_height)

for z in layer_planes:
    # Split mesh at z: keep both halves as separate meshes, track face provenance
    # trimesh.intersections.slice_faces_plane returns the positive-normal side
    pass
```

A cleaner implementation uses `trimesh.graph.connected_components` after splitting to identify layer bands. In practice, for the layer-based painting use case, centroid assignment with a small tolerance is simpler and sufficient:

```python
centroids_z = mesh.triangles_center[:, 2]  # shape: (n_faces,)
layer_indices = np.floor((centroids_z - z_min) / layer_height).astype(int)
```

`mesh.triangles_center` returns the centroid of each face as an (N, 3) array.[^14][^15]

### Step 4: Map Layer Index to Output Extruder

#### Modulus (Cyclic) Palette

```python
def cyclic_palette(layer_idx: int, palette: list[int]) -> int:
    """palette: list of 1-based extruder indices."""
    return palette[layer_idx % len(palette)]
```

Examples:
- Purple: `palette = [1, 2]` (extruder 1 = red, extruder 2 = blue)
- Dark orange: `palette = [1, 1, 3]` (extruder 1 = red, extruder 3 = yellow)

#### Gradient (Frequency-Modulated) Palette

This replicates FullSpectrum's "gradual integer cadence by ratio" algorithm. The idea is to smoothly vary the *density* of one color versus another as Z progresses through a region, rather than snapping to a fixed period.[^16]

Given a transition from color A to color B over a Z range, a normalized position \(t \in [0, 1]\) produces a target ratio \(R = t\) of color B. The layer sequence at ratio \(R\) is built by finding the smallest integer period \(q\) such that \(\lfloor R \cdot q \rceil / q \approx R\), then constructing a pattern of \(q - p\) A's followed by \(p\) B's, where \(p = \text{round}(R \cdot q)\).

The FullSpectrum approach specifically: **the minority color anchors to exactly 1 layer, and the majority color's count scales with the ratio**. So for R=0.25 (25% B), the pattern is B-A-A-A (1 B, 3 A); for R=0.33, it is B-A-A (1 B, 2 A); for R=0.5, it is A-B (1 each). This prevents sudden jumps in cadence.[^16]

```python
def gradient_palette_at_ratio(ratio: float, color_a: int, color_b: int) -> list[int]:
    """
    Returns a repeating palette pattern for blend ratio.
    ratio=0.0 -> all A; ratio=1.0 -> all B
    Uses sequential error diffusion to select colors.
    """
    ratio = max(0.0, min(1.0, ratio))
    if ratio < 0.01: return [color_a]
    if ratio > 0.99: return [color_b]
    # Minority anchors to 1 layer, majority scales
    if ratio <= 0.5:
        minority, majority = color_b, color_a
        period = round(1.0 / ratio) if ratio > 0 else 8
    else:
        minority, majority = color_a, color_b
        period = round(1.0 / (1.0 - ratio)) if ratio < 1 else 8
    pattern = [minority] + [majority] * (period - 1)
    return pattern

def apply_gradient(layer_idx: int, layer_within_region: int, region_total_layers: int,
                   stops: list[tuple[float, int]]) -> int:
    """
    stops: list of (t, extruder_1based) where t in [0.0, 1.0]
    Interpolates between stop pairs to find palette at current layer.
    """
    t = layer_within_region / max(region_total_layers - 1, 1)
    # Find enclosing stop pair
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t0 <= t <= t1:
            local_t = (t - t0) / max(t1 - t0, 1e-9)
            pattern = gradient_palette_at_ratio(local_t, c0, c1)
            return pattern[layer_idx % len(pattern)]
    return stops[-1][^1]
```

### Step 5: Handle Multi-Color Input Mapping

For pre-painted input meshes, each input color maps to its own independent output palette specification. The palette config file (JSON) looks like:

```json
{
  "layer_height_mm": 0.1,
  "target_format": "prusaslicer",
  "color_mappings": [
    {
      "input_extruder": 1,
      "output_palette": {
        "type": "cyclic",
        "pattern": [1, 2]
      }
    },
    {
      "input_extruder": 2,
      "output_palette": {
        "type": "gradient",
        "stops": [[0.0, 3], [1.0, 4]]
      }
    }
  ]
}
```

Each input extruder region is treated independently: its Z extent is measured, and layer indices within that region are computed locally so the gradient or cyclic pattern is applied relative to that region's bottom.

**Key insight**: for gradient palettes, the "region" is contiguous blocks of the same input color, not the global Z of the whole object. A red region from Z=5mm to Z=15mm uses its own local t=0..1 independent of other colors.

### Step 6: Serialize Back to 3MF

Build the output 3MF by:

1. Serializing the (possibly subdivided) mesh back to XML with per-triangle `slic3rpe:mmu_segmentation` attributes
2. Writing `Metadata/Slic3r_PE_model.config` with `extruder value="1"` as default
3. Creating `[Content_Types].xml` and `_rels/.rels` boilerplate
4. Packing everything into a ZIP with the `.3mf` extension

```python
import zipfile, io
from xml.etree.ElementTree import Element, SubElement, tostring

CONTENT_TYPES = '''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>'''

RELS = '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0"
    Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>'''

def write_3mf(output_path, vertices, faces, face_extruders, default_extruder=1,
              target_format="prusaslicer"):
    """Write a 3MF with per-triangle extruder assignments."""
    
    # Build 3dmodel.model XML
    ns_core = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    ns_pe = "http://schemas.slic3r.org/3mf/2017/06"
    
    model = Element("model", attrib={
        "unit": "millimeter",
        "xml:lang": "en-US",
        "xmlns": ns_core,
        "xmlns:slic3rpe": ns_pe,
    })
    resources = SubElement(model, "resources")
    obj = SubElement(resources, "object", attrib={"id": "1", "type": "model"})
    mesh_el = SubElement(obj, "mesh")
    
    verts_el = SubElement(mesh_el, "vertices")
    for v in vertices:
        SubElement(verts_el, "vertex", x=f"{v:.6f}", y=f"{v[^1]:.6f}", z=f"{v[^2]:.6f}")
    
    tris_el = SubElement(mesh_el, "triangles")
    color_attr = "paint_color" if target_format == "bambu" else "slic3rpe:mmu_segmentation"
    for i, face in enumerate(faces):
        attrib = {"v1": str(face), "v2": str(face[^1]), "v3": str(face[^2])}
        ext = face_extruders[i]
        if ext != default_extruder:
            attrib[color_attr] = encode_extruder(ext)
        SubElement(tris_el, "triangle", attrib=attrib)
    
    build = SubElement(model, "build")
    SubElement(build, "item", attrib={"objectid": "1",
        "transform": "1 0 0 0 1 0 0 0 1 0 0 0", "printable": "1"})
    
    model_bytes = tostring(model, encoding="unicode", xml_declaration=True).encode("utf-8")
    
    # Build Slic3r_PE_model.config
    config_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
g>
  <object id="1">
    <metadata type="object" key="extruder" value="{default_extruder}"/>
  </object>
</config>'''.encode("utf-8")
    
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("_rels/.rels", RELS)
        zf.writestr("3D/3dmodel.model", model_bytes)
        zf.writestr("Metadata/Slic3r_PE_model.config", config_xml)
```

***

## Recommended Library Stack

| Layer | Library | Version | Notes |
|-------|---------|---------|-------|
| Mesh loading | `trimesh` | ≥4.x | Pure Python, handles STL/3MF/OBJ; face centroids via `mesh.triangles_center` |
| Numerical operations | `numpy` | ≥1.24 | Layer index binning, face property arrays |
| XML parsing/writing | `xml.etree.ElementTree` (stdlib) or `lxml` | stdlib | `lxml` preferred for namespace-aware round-tripping |
| ZIP packaging | `zipfile` (stdlib) | stdlib | Note: use forward slashes in entry names |
| CLI interface | `click` or `argparse` | stdlib / pip | `click` preferred for ergonomics |
| Config format | `json` (stdlib) | stdlib | Palette config files |

Optional for visualization/preview:
- `open3d` or `vedo`: 3D visualization of the painted result before printing

***

## Handling the Face-Subdivision Problem

When a face spans a Z-layer boundary, assigning it to either layer produces incorrect color at the boundary. Three strategies, in order of increasing correctness:

### Strategy A: Centroid Assignment (Simplest)
Use `mesh.triangles_center[:, 2]` and assign each face to the layer containing its centroid. Faces at boundaries are assigned to whichever layer their centroid falls in. For meshes with many small faces (typical of well-tessellated STLs), boundary faces are a negligible fraction. This is the recommended starting approach.

### Strategy B: Tolerance-Based Threshold
Compute the fraction of each face's area that falls above vs. below each layer boundary. Assign to the majority side. This requires computing face-plane intersection areas, which is moderately complex.

### Strategy C: Mesh Subdivision at Z Planes
Use `trimesh.intersections.slice_faces_plane` iteratively to cut the mesh at each layer boundary, producing a new mesh where no face crosses a boundary. This is the most correct but also the most computationally expensive approach. The `face_index` return value from `trimesh.intersections.mesh_plane` tracks which original face each intersection segment came from, enabling provenance tracking.[^17]

```python
from trimesh.intersections import slice_faces_plane

# Split mesh below and above z=z_level
upper = slice_faces_plane(
    vertices=mesh.vertices, faces=mesh.faces,
    plane_normal=[0, 0, 1], plane_origin=[0, 0, z_level]
)
lower = slice_faces_plane(
    vertices=mesh.vertices, faces=mesh.faces,
    plane_normal=[0, 0, -1], plane_origin=[0, 0, z_level]
)
```

For most use cases, **Strategy A is sufficient** and should be the default, with Strategy C available as an optional `--precise` flag.

***

## The Gradient Algorithm: Mathematical Foundation

The full-spectrum gradient technique is mathematically equivalent to **1D pulse-density modulation (PDM)** or the Bresenham line algorithm applied to layer scheduling.[^3][^16]

Given two filaments A and B and a desired blend ratio \(R\) (fraction of B), the integer layer pattern is constructed as:

\[
\text{use\_B at layer } k \iff \lfloor (k+1) \cdot R \rfloor > \lfloor k \cdot R \rfloor
\]

This is Bresenham-style: accumulate a fractional error and emit a B-layer whenever it overflows. For R = 1/3: layers 0, 3, 6, 9... get B; others get A. For R = 2/3, the opposite.

The FullSpectrum slicer's specific implementation anchors the minority color to period-1 and scales the majority:[^16]
- At R = 0.25: pattern = [B, A, A, A] (period 4)
- At R = 0.5: pattern = [A, B] (period 2)
- At R = 0.75: pattern = [B, B, B, A] (period 4)

For a multi-stop gradient (e.g., red → yellow → blue), each pair of adjacent stops is treated as an independent two-color transition, and the current layer's blend ratio within that stop interval determines the pattern.

***

## Edge Cases and Practical Notes

### Input Color Clustering
STL files have no color information. For single-color STL input, the entire model is treated as input extruder 1, and a single output palette pattern is applied globally.

For 3MF input with multiple painted regions, each region's Z span must be computed independently per region. A region is a set of faces sharing the same input extruder. The region's Z range is `[min(face_centroid_z), max(face_centroid_z)]` for all faces in that region. This allows the gradient to span the full height of each color region independently.

### Multiple Disconnected Islands of the Same Color
If input extruder 1 appears in two disconnected Z ranges (e.g., a base and a top cap with a differently-colored middle), each disconnected contiguous Z range should be treated as a separate region for gradient computation. Use connected-component analysis on face adjacency to separate islands before computing Z extents.

### Output Extruder Count
The number of distinct output extruders referenced in the palette must match the filaments loaded in the slicer. The palette config maps human-readable color names to extruder numbers, and a validator should confirm all referenced extruder numbers are within the configured range (typically 2–6 for multi-material setups).

### Bambu / OrcaSlicer Compatibility
Both BambuStudio and OrcaSlicer accept 3MF files with `paint_color` attributes on triangles[^11][^18]. OrcaSlicer also accepts `slic3rpe:mmu_segmentation` from PrusaSlicer-format files[^12]. The CLI should default to writing both attributes (or allow `--format bambu|prusa|both` flag) to maximize compatibility.

### Tolerance for Z-Level Assignment
Due to floating point and mesh imprecision, use a small epsilon when assigning a face centroid to a layer:

```python
layer_idx = int((face_z - z_min + EPSILON) / layer_height)
```

where `EPSILON = layer_height * 0.01` (1% of layer height) avoids boundary oscillation.

***

## Full Pipeline Summary

```
Input (STL or 3MF)  +  Palette Config (JSON)
        │
        ▼
1. Load mesh geometry (trimesh)
2. Parse per-face input extruder map (xml.etree, from 3MF)
3. Compute face centroid Z values (numpy: mesh.triangles_center[:,2])
4. For each input-color region:
   a. Determine local Z range of that region
   b. Compute layer_index_within_region for each face in region
   c. Apply palette pattern (cyclic OR gradient) to get output_extruder
5. Assemble output face_extruders array (shape: n_faces, dtype: int)
6. Serialize to 3MF XML with per-triangle paint_color / mmu_segmentation
7. Pack into ZIP → rename .3mf

Output: pre-painted .3mf ready for import into OrcaSlicer, BambuStudio,
        PrusaSlicer, or any 3MF-aware slicer
```

The output model, when imported into a slicer with the correct number of filaments loaded, will have every visible surface face already assigned a specific extruder color based on its layer — the slicer simply executes the color assignment rather than computing it.

***

## Limitations

- **Technique is inherently Z-axis aligned**: models with angled geometry (e.g., a 45-degree ramp) will show dithering only where the surface is steep enough to display multiple layers in a single viewing direction.[^5]
- **No sub-triangle precision**: the CLI assigns color at the whole-triangle level, not sub-triangle. This is equivalent to the "fill" paint mode in slicers (full triangle assignment) rather than the "brush" mode (sub-triangle bisection). For layer stratification purposes this is perfectly acceptable and avoids the complex sub-triangle encoding entirely.[^9]
- **Pre-existing sub-painted regions**: if the input 3MF contains sub-triangle painted regions (long `mmu_segmentation` strings), these should be either preserved as-is or detected and flattened to the dominant extruder before processing.
- **Slicer must support painted 3MF**: this approach requires the target slicer to interpret `paint_color` / `mmu_segmentation` triangle attributes. All major modern slicers (OrcaSlicer, BambuStudio, PrusaSlicer 2.x+) do.[^19][^18]

---

## References

1. [Full Spectrum for Snapmaker Orca: 10+ Colors with Only 4 Filaments - No AMS Needed!](https://www.reddit.com/r/snapmaker/comments/1rkpj7l/full_spectrum_for_snapmaker_orca_10_colors_with/) - Full Spectrum for Snapmaker Orca: 10+ Colors with Only 4 Filaments - No AMS Needed!

2. [FullSpectrum Printing on the Snapmaker U1](https://www.youtube.com/watch?v=uE1Su-FUvls) - From the Snapmaker community: We're 3D printing rainbows with 4 tools! Part 1 video on the "FullSpec...

3. [38 Color FDM 3D Print 🌈 - Full Spectrum OrcaSlicer](https://www.youtube.com/watch?v=cDCryAJJDiM)

4. [ratdoux/OrcaSlicer-FullSpectrum: G-code generator for ... - GitHub](https://github.com/ratdoux/OrcaSlicer-FullSpectrum) - This fork adds support for virtual mixed-color filaments, enabling you to create new colors by alter...

5. [4 Filaments, ALL The Colors - Full Spectrum - YouTube](https://www.youtube.com/watch?v=Mjdwu-Ga_rA) - Full color CYMK printing on a normal FDM printer sounds like a pipe dream... but now it's a reality,...

6. [Full Spectrum (Full Color) slicer fork of Snapmaker Orca, inspired by Aceman11100](https://www.reddit.com/r/snapmaker/comments/1r0i56r/full_spectrum_full_color_slicer_fork_of_snapmaker/) - Full Spectrum (Full Color) slicer fork of Snapmaker Orca, inspired by Aceman11100

7. [Full Spectrum Mod Tutorial/How-to for Bambu Lab Printers (filament ...](https://www.reddit.com/r/BambuLab/comments/1s4q0ja/video_full_spectrum_mod_tutorialhowto_for_bambu/) - For example, by if a user has red filament and yellow filament, the two colors can be alternated by ...

8. [Really loving the full spectrum fork of Orca Slicer](https://www.reddit.com/r/SnapmakerU1/comments/1s1judl/really_loving_the_full_spectrum_fork_of_orca/) - Really loving the full spectrum fork of Orca Slicer

9. [3mf file color specification what I have found V2 - Printables.com](https://www.printables.com/article/3mf-file-color-specification-what-i-have-found-v4-YNYjaE5?from=home)

10. [spec_core/3MF Core Specification.md at master](https://github.com/3MFConsortium/spec_core/blob/master/3MF%20Core%20Specification.md) - 3MF's Core specification. Contribute to 3MFConsortium/spec_core development by creating an account o...

11. [Import 3MF files from Bambu Slicer with Color Data for Rendering](https://www.reddit.com/r/blenderhelp/comments/1buacp1/import_3mf_files_from_bambu_slicer_with_color/)

12. [3D Printing Tips and Tricks - Catharsis - Google Groups](https://groups.google.com/g/3d-printing-tips--tricks/c/c-bqWxba6wU/m/Qyzdhh5cBgAJ)

13. [GitHub - mikedh/trimesh: Python library for loading and using ...](https://github.com/mikedh/trimesh) - Trimesh is a pure Python 3.8+ library for loading and using triangular meshes with an emphasis on wa...

14. [trimesh 4.11.5 documentation](https://trimesh.org/trimesh.html)

15. [trimesh.base - trimesh 4.11.5 documentation](https://trimesh.org/trimesh.base.html)

16. [v0.92-alpha · ratdoux OrcaSlicer-FullSpectrum · Discussion #20](https://github.com/ratdoux/OrcaSlicer-FullSpectrum/discussions/20) - Fixed paint/index remapping when adding physical or virtual filaments so existing painted mixed regi...

17. [trimesh.intersections - trimesh 4.11.5 documentation](https://trimesh.org/trimesh.intersections.html) - A utility function for slicing a mesh by multiple parallel planes which caches the dot product opera...

18. [CLI segfault when slicing 3MF with paint_color and --load-filaments ...](https://github.com/OrcaSlicer/OrcaSlicer/issues/12426) - Create or open a 3MF with per-triangle paint_color attributes (e.g. from multi-colour painting in th...

19. [Bambu 3MF - kept colour painting · Issue #12502 · prusa3d/PrusaSlicer](https://github.com/prusa3d/PrusaSlicer/issues/12502) - Is your feature request related to a problem? Please describe. 2.7.3 now opens a Bambu 3MF, which is...

