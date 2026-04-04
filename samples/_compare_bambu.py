"""Compare our output vs Bambu reference: decode a single face tree from each."""
import zipfile
import numpy as np
from lxml import etree
from full_spectrum.mesh import load_mesh

NS = 'http://schemas.slic3r.org/3mf/2017/06'


def get_face_hex(filename, face_idx):
    """Extract hex string for a given face from a 3mf file."""
    zf = zipfile.ZipFile(filename)
    root = etree.fromstring(zf.read('3D/3dmodel.model'))

    # Find triangle elements
    ns_3mf = 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
    tris = list(root.iter(f'{{{ns_3mf}}}triangle'))
    if face_idx < len(tris):
        seg = tris[face_idx].get(f'{{{NS}}}mmu_segmentation')
        return seg
    return None


def decode_nibbles(hex_str):
    """Decode hex string to nibble array (root at end → reverse)."""
    return [int(c, 16) for c in reversed(hex_str)]


def count_split_types(nibbles, pos=0, depth=0):
    """Walk nibble tree, count split types."""
    if pos >= len(nibbles):
        return {'1': 0, '2': 0, '3': 0, 'leaves': 0, 'max_depth': depth}, pos
    n = nibbles[pos]
    split = n & 0x3
    upper = (n >> 2) & 0x3

    if split == 0:
        consumed = 2 if upper == 3 else 1
        return {'1': 0, '2': 0, '3': 0, 'leaves': 1, 'max_depth': depth}, pos + consumed

    counts = {'1': 0, '2': 0, '3': 0, 'leaves': 0, 'max_depth': depth}
    counts[str(split)] += 1
    num_children = split + 1
    next_pos = pos + 1
    for _ in range(num_children):
        child_counts, next_pos = count_split_types(nibbles, next_pos, depth + 1)
        for k in ['1', '2', '3', 'leaves']:
            counts[k] += child_counts[k]
        counts['max_depth'] = max(counts['max_depth'], child_counts['max_depth'])
    return counts, next_pos


# Compare both files for the same face index
for face_idx in [2, 3, 10, 11]:
    # Our output
    our_hex = get_face_hex('samples/cylinder_painted.3mf', face_idx)
    # Bambu reference
    bambu_hex = get_face_hex('samples/cylinder_bambu_painted.3mf', face_idx)

    print(f"=== Face {face_idx} ===")
    if our_hex:
        our_nibs = decode_nibbles(our_hex)
        our_stats, _ = count_split_types(our_nibs)
        print(f"  Ours:  len={len(our_hex)}, 1sp={our_stats['1']}, 2sp={our_stats['2']}, "
              f"3sp={our_stats['3']}, leaves={our_stats['leaves']}, depth={our_stats['max_depth']}")
    else:
        print("  Ours:  No segmentation data")

    if bambu_hex:
        bambu_nibs = decode_nibbles(bambu_hex)
        bambu_stats, _ = count_split_types(bambu_nibs)
        print(f"  Bambu: len={len(bambu_hex)}, 1sp={bambu_stats['1']}, 2sp={bambu_stats['2']}, "
              f"3sp={bambu_stats['3']}, leaves={bambu_stats['leaves']}, depth={bambu_stats['max_depth']}")
    else:
        print("  Bambu: No segmentation data")

    if our_hex and bambu_hex:
        print(f"  Match: {our_hex == bambu_hex}")
    print()

# Also check: what split type does the root of our tree use?
print("=== Root nibble analysis (first 5 boundary faces) ===")
boundary_faces = []
mesh = load_mesh('./samples/cylinder.3mf')
for i in range(len(mesh.faces)):
    fv = mesh.vertices[mesh.faces[i]]
    z_span = fv[:, 2].max() - fv[:, 2].min()
    if z_span > 0.001:
        boundary_faces.append(i)
        if len(boundary_faces) >= 5:
            break

for fidx in boundary_faces:
    our_hex = get_face_hex('samples/cylinder_painted.3mf', fidx)
    bambu_hex = get_face_hex('samples/cylinder_bambu_painted.3mf', fidx)
    if our_hex:
        root_nib = int(our_hex[-1], 16)
        split_type = root_nib & 0x3
        special = (root_nib >> 2) & 0x3
        print(f"  Face {fidx} ours:  root=0x{our_hex[-1]}, split={split_type}, special={special}")
    if bambu_hex:
        root_nib = int(bambu_hex[-1], 16)
        split_type = root_nib & 0x3
        special = (root_nib >> 2) & 0x3
        print(f"  Face {fidx} bambu: root=0x{bambu_hex[-1]}, split={split_type}, special={special}")
    print()
