"""Deep analysis: are adjacent face sub-triangles consistent at layer boundaries?"""
import numpy as np
import math
from full_spectrum.mesh import load_mesh
from full_spectrum.encoding import LeafNode, SplitNode
from full_spectrum.subdivision import subdivide_triangle

mesh = load_mesh('./samples/cylinder.3mf')
lh = 0.1
gzmin = float(mesh.vertices[:, 2].min())
epsilon = lh * 0.001
verts = mesh.vertices
faces = mesh.faces

# Find pairs of faces sharing a vertical edge
# On a cylinder, boundary faces come in pairs (quad → 2 triangles)
# Look at face 2 and face 3
for fidx in [2, 3]:
    fv = verts[faces[fidx]]
    print(f"Face {fidx}:")
    for i in range(3):
        print(f"  v{i} = ({fv[i,0]:.6f}, {fv[i,1]:.6f}, {fv[i,2]:.6f})")
    z_sorted = sorted(fv[:, 2])
    print(f"  Z sorted: [{z_sorted[0]:.4f}, {z_sorted[1]:.4f}, {z_sorted[2]:.4f}]")
    print()

# How many distinct Z-values exist among all vertices?
all_z = verts[:, 2]
unique_z = np.unique(all_z)
print(f"Unique Z values: {len(unique_z)}")
if len(unique_z) <= 10:
    print(f"Z values: {unique_z}")
else:
    print(f"Z range: [{unique_z[0]:.6f}, {unique_z[-1]:.6f}]")

# Check if there's Z variation within "horizontal" edges
# Get all boundary faces (ones with z_span > 0)
print("\n=== Face pair analysis ===")
# Group boundary faces by their vertex Z patterns
from collections import defaultdict

face_types = defaultdict(list)
for i in range(len(faces)):
    fv = verts[faces[i]]
    zs = tuple(sorted(fv[:, 2]))
    z_span = zs[2] - zs[0]
    if z_span > 0.001:
        # Classify: "2-top-1-bottom" vs "1-top-2-bottom"
        if abs(zs[1] - zs[2]) < 0.001:
            face_types["2-top-1-bottom"].append(i)
        elif abs(zs[0] - zs[1]) < 0.001:
            face_types["1-top-2-bottom"].append(i)
        else:
            face_types["all-different"].append(i)

for ftype, indices in face_types.items():
    print(f"{ftype}: {len(indices)} faces")

# For two representative faces (one of each type), trace the first few splits
# and check if the cut Z-positions are identical
print("\n=== Cut Z-position comparison between adj face types ===")
face_a_idx = face_types.get("2-top-1-bottom", [None])[0]
face_b_idx = face_types.get("1-top-2-bottom", [None])[0]

if face_a_idx is not None and face_b_idx is not None:
    for fidx, ftype in [(face_a_idx, "2T1B"), (face_b_idx, "1T2B")]:
        fv = verts[faces[fidx]]
        zs = sorted(fv[:, 2])
        z_top = zs[2]
        z_bot = zs[0]
        print(f"  Face {fidx} ({ftype}): z_top={z_top:.4f}, z_bot={z_bot:.4f}")
        # First 2-split cut: midpoints of vertical edges
        # Both midpoints should be at (z_top + z_bot) / 2
        mid_z = (z_top + z_bot) / 2
        print(f"    L1 cut at z = {mid_z:.4f}")
        # Second level cuts
        print(f"    L2 cuts at z = {(z_top + mid_z)/2:.4f} and {(mid_z + z_bot)/2:.4f}")
        # Third level
        q1 = (z_top + mid_z) / 2
        q3 = (mid_z + z_bot) / 2
        print(f"    L3 cuts at z = {(z_top+q1)/2:.4f}, {(q1+mid_z)/2:.4f}, "
              f"{(mid_z+q3)/2:.4f}, {(q3+z_bot)/2:.4f}")

# Key question: at depth 9 (max), are there leaves with z_span crossing a layer boundary
# where the centroid position differs between faces of different types?
# A leaf centered at z=N*lh (exactly on boundary) will be assigned to layer N.
# If an adjacent face's leaf is centered at z=N*lh - epsilon, it gets layer N-1.
print("\n=== Layer boundary alignment analysis ===")
# Layer boundaries at gzmin + k * lh
# Binary cuts at gzmin + m * (33/512) for integers m
# Find layer boundaries that DON'T align with binary cuts
layer_boundaries = []
for k in range(1, 330):
    z_boundary = gzmin + k * lh
    # Nearest binary cut
    binary_step = 33.0 / 512  # depth 9
    nearest_cut = gzmin + round((z_boundary - gzmin) / binary_step) * binary_step
    offset = abs(z_boundary - nearest_cut)
    layer_boundaries.append((k, z_boundary, nearest_cut, offset))

# Sort by offset (worst alignment first)
layer_boundaries.sort(key=lambda x: -x[3])
print("Top 10 worst-aligned layer boundaries:")
for k, zb, nc, off in layer_boundaries[:10]:
    print(f"  Layer {k}: boundary z={zb:.6f}, nearest cut z={nc:.6f}, offset={off:.6f} mm")
print(f"\nBest aligned:")
for k, zb, nc, off in layer_boundaries[-5:]:
    print(f"  Layer {k}: boundary z={zb:.6f}, nearest cut z={nc:.6f}, offset={off:.6f} mm")

# How many layer boundaries have offset > some threshold?
for thresh in [0.01, 0.02, 0.03]:
    count = sum(1 for _, _, _, off in layer_boundaries if off > thresh)
    print(f"Layer boundaries with offset > {thresh}mm: {count} / 329")
