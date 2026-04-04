"""Validate our encoding vs Bambu expected output."""
import zipfile
import numpy as np
from lxml import etree
from full_spectrum.mesh import load_mesh, compute_face_layers
from full_spectrum.subdivision import find_boundary_faces, _make_subdivider, _face_to_hex
from full_spectrum.encoding import filament_to_hex


def decode_tree_dfs(nibbles, pos=0, depth=0):
    """Decode a nibble stream into a tree structure (DFS, children in reverse order)."""
    if pos >= len(nibbles):
        return None, pos
    n = nibbles[pos]
    split = n & 0x3
    upper = (n >> 2) & 0x3

    if split == 0:
        if upper == 3:
            # Extended leaf: next nibble is state-3
            if pos + 1 < len(nibbles):
                ext_state = nibbles[pos + 1] + 3
                return {"type": "leaf", "state": ext_state, "depth": depth}, pos + 2
            return {"type": "leaf", "state": "ERR", "depth": depth}, pos + 1
        else:
            return {"type": "leaf", "state": upper, "depth": depth}, pos + 1
    else:
        n_children = {1: 2, 2: 3, 3: 4}[split]
        children = []
        p = pos + 1
        # Children are stored in REVERSE order
        for _ in range(n_children):
            child, p = decode_tree_dfs(nibbles, p, depth + 1)
            children.append(child)
        children.reverse()  # Undo reverse storage
        return {
            "type": "split",
            "split_sides": split,
            "special_side": upper,
            "children": children,
            "depth": depth,
        }, p


def count_leaf_states(node):
    """Count leaf states in a decoded tree."""
    if node is None:
        return {}
    if node["type"] == "leaf":
        s = node["state"]
        return {s: 1}
    counts = {}
    for c in node["children"]:
        for k, v in count_leaf_states(c).items():
            counts[k] = counts.get(k, 0) + v
    return counts


def main():
    # Load our output
    with zipfile.ZipFile("./cylinder_out.3mf") as zf:
        data = zf.read("3D/3dmodel.model")
    root = etree.fromstring(data)
    ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    tris = root.findall(".//m:triangle", ns)

    painted = [(i, t.get("paint_color")) for i, t in enumerate(tris) if t.get("paint_color")]
    print(f"Painted triangles: {len(painted)}")

    # Decode a few faces
    for face_idx, hex_str in painted[:3]:
        nibbles = [int(c, 16) for c in hex_str]
        tree, consumed = decode_tree_dfs(nibbles)
        print(f"\nFace {face_idx}: hex_len={len(hex_str)}, consumed={consumed}")
        states = count_leaf_states(tree)
        total = sum(states.values())
        print(f"  Leaf states: {states}, total leaves: {total}")
        for s, cnt in sorted(states.items()):
            print(f"    State {s}: {cnt} leaves ({100*cnt/total:.1f}%)")

    # Now decode ALL painted faces and check state distribution
    print("\n--- Aggregate across all painted faces ---")
    all_states = {}
    for face_idx, hex_str in painted:
        nibbles = [int(c, 16) for c in hex_str]
        tree, consumed = decode_tree_dfs(nibbles)
        states = count_leaf_states(tree)
        for s, cnt in states.items():
            all_states[s] = all_states.get(s, 0) + cnt
    total = sum(all_states.values())
    print(f"Total leaves across all faces: {total}")
    for s, cnt in sorted(all_states.items()):
        print(f"  State {s}: {cnt} leaves ({100*cnt/total:.1f}%)")

    # What states SHOULD we see?
    # filament 1 -> state 0, filament 2 -> state 1
    # For 0.1mm layers on a 33mm cylinder, ~50% should be each
    print(f"\nExpected: ~50% state 0 (filament 1), ~50% state 1 (filament 2)")

    # Check: what do filament_to_hex produce?
    print(f"\nfilament_to_hex(1) = {filament_to_hex(1)}")
    print(f"filament_to_hex(2) = {filament_to_hex(2)}")

    # Verify: what states does subdivision assign?
    mesh = load_mesh("./cylinder.3mf")
    lh = 0.1
    gzmin = float(mesh.triangles_center[:, 2].min())
    vmax = float(mesh.vertices[:, 2].max())
    eps = lh * 0.001
    ml = max(0, int(np.floor((vmax - gzmin + eps) / lh)))
    fm = {l: (l % 2) + 1 for l in range(ml + 1)}

    # What does the subdivider produce for filament=1 and filament=2?
    # In Bambu encoding: state = filament - 1
    # filament 1 -> state 0, filament 2 -> state 1
    # So leaf nibble for state 0 = (0 << 2) | 0 = 0x0
    # And leaf nibble for state 1 = (1 << 2) | 0 = 0x4
    # But in BambuStudio, state is the "EnforcerBlockerType" enum:
    #   0 = NONE, 1 = ENFORCER, 2 = BLOCKER, etc.
    # The mapping from filament to state might be off

    # Let's check what our code puts as the leaf state
    sub = _make_subdivider(lh, gzmin, fm, 1, 9, eps)
    afv = mesh.vertices[mesh.faces].astype(np.float64)
    
    # Get boundary faces
    li = compute_face_layers(mesh, lh)
    bm = find_boundary_faces(mesh, li, lh, gzmin)
    bi = np.nonzero(bm)[0]

    hex_str = _face_to_hex(sub, afv[bi[0]], 9)
    nibbles = [int(c, 16) for c in hex_str]
    tree, _ = decode_tree_dfs(nibbles)
    states = count_leaf_states(tree)
    print(f"\nOur encoding for face {bi[0]}:")
    print(f"  Leaf states: {states}")

    # And the flat face hex
    for fil in [1, 2]:
        h = filament_to_hex(fil)
        n = int(h, 16)
        state = (n >> 2) & 0x3
        print(f"  filament {fil} -> hex '{h}' -> nibble 0x{n:X} -> state {state}")


if __name__ == "__main__":
    main()
