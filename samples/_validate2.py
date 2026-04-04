"""Validate encoding: decode hex trees properly (root at END of string)."""
import zipfile
import numpy as np
from lxml import etree
from full_spectrum.mesh import load_mesh
from full_spectrum.encoding import filament_to_hex


def decode_tree(hex_str):
    """Decode a hex string into a tree. Root is at the END (reversed nibble order)."""
    # Convert hex string to nibble vector, reversed (root first)
    nibbles = [int(c, 16) for c in reversed(hex_str)]
    tree, consumed = _decode_dfs(nibbles, 0, 0)
    return tree, consumed, len(nibbles)


def _decode_dfs(nibbles, pos, depth):
    if pos >= len(nibbles):
        return {"type": "error", "msg": "out of bounds", "depth": depth}, pos
    n = nibbles[pos]
    split = n & 0x3
    upper = (n >> 2) & 0x3

    if split == 0:
        if upper == 3:  # 0xC = extended leaf
            if pos + 1 < len(nibbles):
                state = nibbles[pos + 1] + 3
                return {"type": "leaf", "state": state, "depth": depth}, pos + 2
            return {"type": "leaf", "state": "ERR_EXT", "depth": depth}, pos + 1
        return {"type": "leaf", "state": upper, "depth": depth}, pos + 1

    n_children = {1: 2, 2: 3, 3: 4}[split]
    children = []
    p = pos + 1
    # Children stored in reverse order in the stream — decode and un-reverse
    for _ in range(n_children):
        child, p = _decode_dfs(nibbles, p, depth + 1)
        children.append(child)
    children.reverse()  # Un-reverse to get original order
    return {
        "type": "split",
        "split_sides": split,
        "special_side": upper,
        "children": children,
        "depth": depth,
    }, p


def count_states(node):
    if node is None or node.get("type") == "error":
        return {}
    if node["type"] == "leaf":
        return {node["state"]: 1}
    counts = {}
    for c in node["children"]:
        for k, v in count_states(c).items():
            counts[k] = counts.get(k, 0) + v
    return counts


def tree_depth(node):
    if node is None or node["type"] == "leaf":
        return 0
    return 1 + max(tree_depth(c) for c in node["children"])


def tree_summary(node, indent=0):
    """Short summary of top levels."""
    prefix = "  " * indent
    if node["type"] == "leaf":
        return f"{prefix}Leaf(state={node['state']})"
    split_names = {1: "1-split", 2: "2-split", 3: "3-split"}
    lines = [f"{prefix}{split_names[node['split_sides']]}(special={node['special_side']})"]
    if indent < 3:  # Show first 3 levels
        for i, c in enumerate(node["children"]):
            lines.append(f"{prefix}  child[{i}]:")
            lines.append(tree_summary(c, indent + 2))
    else:
        states = count_states(node)
        total = sum(states.values())
        lines.append(f"{prefix}  [{total} leaves: {dict(sorted(states.items()))}]")
    return "\n".join(lines)


def main():
    with zipfile.ZipFile("./cylinder_out.3mf") as zf:
        data = zf.read("3D/3dmodel.model")
    root = etree.fromstring(data)
    ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    tris = root.findall(".//m:triangle", ns)

    painted = [(i, t.get("paint_color")) for i, t in enumerate(tris) if t.get("paint_color")]
    print(f"Painted triangles: {len(painted)}")

    # Show first hex string ends
    hex0 = painted[0][1]
    print(f"\nFace {painted[0][0]}: hex_len={len(hex0)}")
    print(f"  First 40 chars: {hex0[:40]}")
    print(f"  Last  40 chars: {hex0[-40:]}")

    # Decode properly (root at end)
    for face_idx, hex_str in painted[:3]:
        tree, consumed, total = decode_tree(hex_str)
        states = count_states(tree)
        total_leaves = sum(states.values())
        depth = tree_depth(tree)
        print(f"\nFace {face_idx}: hex_len={len(hex_str)}, consumed={consumed}/{total}")
        print(f"  Depth: {depth}, total leaves: {total_leaves}")
        print(f"  States: {dict(sorted(states.items()))}")
        for s, cnt in sorted(states.items()):
            pct = 100 * cnt / total_leaves if total_leaves else 0
            print(f"    State {s}: {cnt} ({pct:.1f}%)")
        print(f"  Tree structure:")
        print(tree_summary(tree))

    # Aggregate
    print("\n--- Aggregate ---")
    all_states = {}
    for face_idx, hex_str in painted:
        tree, _, _ = decode_tree(hex_str)
        for s, cnt in count_states(tree).items():
            all_states[s] = all_states.get(s, 0) + cnt
    total_all = sum(all_states.values())
    print(f"Total leaves: {total_all}")
    for s, cnt in sorted(all_states.items()):
        print(f"  State {s}: {cnt} ({100*cnt/total_all:.1f}%)")

    # Expected: filament 1 -> state 1, filament 2 -> state 2
    # should be ~50/50 for alternating layers
    print(f"\nExpected: ~50% state 1 (filament 1), ~50% state 2 (filament 2)")
    print(f"filament_to_hex(1) = '{filament_to_hex(1)}' = nibble {int(filament_to_hex(1), 16)}")
    print(f"filament_to_hex(2) = '{filament_to_hex(2)}' = nibble {int(filament_to_hex(2), 16)}")


if __name__ == "__main__":
    main()
