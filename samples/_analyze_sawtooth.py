"""Analyze leaf-level sub-triangle Z-spans to find straddling leaves causing sawtooth."""
import numpy as np
import math
from collections import Counter
from full_spectrum.mesh import load_mesh
from full_spectrum.encoding import LeafNode, SplitNode
from full_spectrum.subdivision import subdivide_triangle

mesh = load_mesh('./samples/cylinder.3mf')
lh = 0.1
gzmin = float(mesh.vertices[:, 2].min())
epsilon = lh * 0.001

fv = mesh.vertices[mesh.faces[2]].astype(np.float64)
node = subdivide_triangle(fv, lh, gzmin, {i: (i % 2) + 1 for i in range(400)}, 1, max_depth=9)


def _mid(a, b):
    return ((a[0]+b[0])*0.5, (a[1]+b[1])*0.5, (a[2]+b[2])*0.5)


def analyze_leaves(n, v0, v1, v2, depth=0):
    results = []
    if isinstance(n, LeafNode):
        zs = [v0[2], v1[2], v2[2]]
        z_lo, z_hi = min(zs), max(zs)
        z_span = z_hi - z_lo
        cz = sum(zs) / 3.0
        layer_lo = max(0, math.floor((z_lo - gzmin + epsilon) / lh))
        layer_hi = max(0, math.floor((z_hi - gzmin + epsilon) / lh))
        straddle = layer_lo != layer_hi
        results.append({
            'depth': depth, 'z_span': z_span, 'z_lo': z_lo, 'z_hi': z_hi,
            'centroid_z': cz, 'layer_lo': layer_lo, 'layer_hi': layer_hi,
            'straddle': straddle, 'state': n.state
        })
        return results

    if n.split_sides == 3:
        m01, m12, m20 = _mid(v0, v1), _mid(v1, v2), _mid(v2, v0)
        results += analyze_leaves(n.children[0], v0, m01, m20, depth+1)
        results += analyze_leaves(n.children[1], m01, v1, m12, depth+1)
        results += analyze_leaves(n.children[2], m12, v2, m20, depth+1)
        results += analyze_leaves(n.children[3], m01, m12, m20, depth+1)
    elif n.split_sides == 2:
        s = n.special_side
        if s == 2:
            m12, m20 = _mid(v1, v2), _mid(v2, v0)
            results += analyze_leaves(n.children[0], v2, m20, m12, depth+1)
            results += analyze_leaves(n.children[1], m20, v0, m12, depth+1)
            results += analyze_leaves(n.children[2], v0, v1, m12, depth+1)
        elif s == 0:
            m01, m20 = _mid(v0, v1), _mid(v2, v0)
            results += analyze_leaves(n.children[0], v0, m01, m20, depth+1)
            results += analyze_leaves(n.children[1], m01, v1, m20, depth+1)
            results += analyze_leaves(n.children[2], v1, v2, m20, depth+1)
        else:  # s == 1
            m01, m12 = _mid(v0, v1), _mid(v1, v2)
            results += analyze_leaves(n.children[0], v1, m12, m01, depth+1)
            results += analyze_leaves(n.children[1], m12, v2, m01, depth+1)
            results += analyze_leaves(n.children[2], v2, v0, m01, depth+1)
    return results


leaves = analyze_leaves(node, tuple(fv[0]), tuple(fv[1]), tuple(fv[2]))
straddling = [l for l in leaves if l['straddle']]
print(f"Total leaves: {len(leaves)}")
print(f"Straddling leaves: {len(straddling)}")
max_depth = max(l['depth'] for l in leaves)
print(f"Max leaf depth: {max_depth}")
dc = Counter(l['depth'] for l in leaves)
print("Depth distribution:", " ".join(f"d{d}={dc[d]}" for d in sorted(dc)))
print(f"Max z_span: {max(l['z_span'] for l in leaves):.6f} mm")
print(f"Min z_span: {min(l['z_span'] for l in leaves):.6f} mm")

if straddling:
    print(f"\nStraddling leaf examples (first 10):")
    for s in straddling[:10]:
        print(f"  depth={s['depth']}, z=[{s['z_lo']:.4f}, {s['z_hi']:.4f}], "
              f"span={s['z_span']:.4f}, layers=[{s['layer_lo']},{s['layer_hi']}], "
              f"state={s['state']}")

# Now compare two adjacent faces (faces 2 and 3) at a specific Z boundary
print("\n=== Comparing adjacent faces at shared boundary ===")
for face_idx in [2, 3]:
    fv2 = mesh.vertices[mesh.faces[face_idx]].astype(np.float64)
    node2 = subdivide_triangle(fv2, lh, gzmin, {i: (i % 2) + 1 for i in range(400)}, 1, max_depth=9)
    leaves2 = analyze_leaves(node2, tuple(fv2[0]), tuple(fv2[1]), tuple(fv2[2]))
    straddling2 = [l for l in leaves2 if l['straddle']]
    z_spans = [l['z_span'] for l in leaves2]
    print(f"Face {face_idx}: {len(leaves2)} leaves, {len(straddling2)} straddling, "
          f"max_zspan={max(z_spans):.6f}, max_depth={max(l['depth'] for l in leaves2)}")
