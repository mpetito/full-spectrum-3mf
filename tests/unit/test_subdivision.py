"""Tests for boundary face detection and recursive bisection tree construction."""

from __future__ import annotations

import numpy as np
import pytest
import trimesh

from full_spectrum.encoding import (
    LeafNode,
    SplitNode,
    decode_bisection_tree,
    encode_bisection_tree,
)
from full_spectrum.subdivision import (
    encode_boundary_faces,
    find_boundary_faces,
    subdivide_triangle,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_leaves(node) -> list[int]:
    """Collect all leaf states from a bisection tree."""
    if isinstance(node, LeafNode):
        return [node.state]
    if isinstance(node, SplitNode):
        result: list[int] = []
        for child in node.children:
            result.extend(_collect_leaves(child))
        return result
    raise TypeError(f"Unknown node type: {type(node)}")


def _tree_depth(node) -> int:
    """Return the maximum depth of a bisection tree (0 for a leaf)."""
    if isinstance(node, LeafNode):
        return 0
    if isinstance(node, SplitNode):
        return 1 + max(_tree_depth(c) for c in node.children)
    raise TypeError(f"Unknown node type: {type(node)}")


# ---------------------------------------------------------------------------
# find_boundary_faces
# ---------------------------------------------------------------------------


class TestFindBoundaryFaces:
    def test_flat_mesh_no_boundaries(self):
        """All faces lie flat at z=0 within a single layer -> no boundaries."""
        vertices = np.array([
            [0, 0, 0], [1, 0, 0], [0, 1, 0],
            [1, 1, 0], [2, 0, 0], [2, 1, 0],
        ], dtype=np.float64)
        faces = np.array([[0, 1, 2], [3, 4, 5]], dtype=np.int32)
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        layer_indices = np.array([0, 0])
        mask = find_boundary_faces(mesh, layer_indices, layer_height=0.2, global_z_min=0.0)
        assert mask.shape == (2,)
        assert not mask.any()

    def test_some_faces_cross_boundary(self):
        """Faces spanning across the layer boundary are detected."""
        vertices = np.array([
            [0, 0, 0.0],   # v0
            [1, 0, 0.0],   # v1
            [0, 1, 0.05],  # v2 — within layer 0 (height=0.1)
            [0, 0, 0.0],   # v3
            [1, 0, 0.0],   # v4
            [0, 1, 0.15],  # v5 — crosses into layer 1
        ], dtype=np.float64)
        faces = np.array([[0, 1, 2], [3, 4, 5]], dtype=np.int32)
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        layer_indices = np.array([0, 0])  # both assigned to layer 0 by centroid
        mask = find_boundary_faces(mesh, layer_indices, layer_height=0.1, global_z_min=0.0)
        assert mask.shape == (2,)
        assert not mask[0], "Face 0 is within layer 0"
        assert mask[1], "Face 1 crosses into layer 1"

    def test_epsilon_tolerance(self):
        """Face barely touching the boundary edge (within epsilon) is NOT boundary."""
        layer_height = 0.1
        epsilon = layer_height * 0.001  # 0.0001
        # band for layer 0: [0.0, 0.1]
        # vertex at 0.1 + epsilon/2 is within tolerance
        vertices = np.array([
            [0, 0, 0.0],
            [1, 0, 0.0],
            [0, 1, 0.1 + epsilon / 2],
        ], dtype=np.float64)
        faces = np.array([[0, 1, 2]], dtype=np.int32)
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        layer_indices = np.array([0])
        mask = find_boundary_faces(mesh, layer_indices, layer_height=layer_height, global_z_min=0.0)
        assert not mask[0], "Within epsilon tolerance"

    def test_all_boundary_faces(self):
        """Every face crosses a boundary → all True."""
        vertices = np.array([
            [0, 0, 0.0], [1, 0, 0.0], [0.5, 0.5, 0.2],
            [0, 0, 0.0], [1, 0, 0.0], [0.5, 0.5, 0.2],
        ], dtype=np.float64)
        faces = np.array([[0, 1, 2], [3, 4, 5]], dtype=np.int32)
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        # Centroids at z ≈ 0.067, assigned to layer 0
        layer_indices = np.array([0, 0])
        mask = find_boundary_faces(mesh, layer_indices, layer_height=0.1, global_z_min=0.0)
        assert mask.all()


# ---------------------------------------------------------------------------
# subdivide_triangle
# ---------------------------------------------------------------------------


class TestSubdivideTriangle:
    def test_single_layer_returns_leaf(self):
        """Triangle entirely within one layer → LeafNode, no split."""
        verts = np.array([
            [0, 0, 0.01],
            [1, 0, 0.02],
            [0, 1, 0.03],
        ], dtype=np.float64)
        filament_map = {0: 2}
        node = subdivide_triangle(verts, 0.1, 0.0, filament_map, default_filament=1)
        assert isinstance(node, LeafNode)
        assert node.state == 2

    def test_two_layer_triangle(self):
        """Triangle spanning two layers → at least one split, 2+ leaves."""
        verts = np.array([
            [0, 0, 0.0],
            [1, 0, 0.0],
            [0.5, 0.5, 0.15],
        ], dtype=np.float64)
        filament_map = {0: 1, 1: 2}
        node = subdivide_triangle(verts, 0.1, 0.0, filament_map, default_filament=1)
        leaves = _collect_leaves(node)
        assert len(leaves) >= 2
        assert set(leaves) <= {1, 2}

    def test_two_layer_encodes_decodes(self):
        """Encode/decode round-trip for a 2-layer split."""
        verts = np.array([
            [0, 0, 0.0],
            [1, 0, 0.0],
            [0.5, 0.5, 0.15],
        ], dtype=np.float64)
        filament_map = {0: 1, 1: 2}
        node = subdivide_triangle(verts, 0.1, 0.0, filament_map, default_filament=1)
        hex_str = encode_bisection_tree(node)
        decoded = decode_bisection_tree(hex_str)
        assert decoded == node

    def test_multi_layer_triangle(self):
        """Triangle spanning 4 layers → multiple splits, ~4+ leaves."""
        verts = np.array([
            [0, 0, 0.0],
            [1, 0, 0.0],
            [0.5, 0.5, 0.35],  # spans layers 0,1,2,3
        ], dtype=np.float64)
        filament_map = {0: 1, 1: 2, 2: 1, 3: 2}
        node = subdivide_triangle(verts, 0.1, 0.0, filament_map, default_filament=1)
        leaves = _collect_leaves(node)
        assert len(leaves) >= 4
        assert set(leaves) <= {1, 2}

    def test_tall_triangle_convergence(self):
        """Tall triangle (20 layers) converges within max_depth=12."""
        verts = np.array([
            [0, 0, 0.0],
            [1, 0, 0.0],
            [0.5, 0.5, 2.0],  # 20 layers at 0.1mm
        ], dtype=np.float64)
        filament_map = {i: (i % 2) + 1 for i in range(20)}
        node = subdivide_triangle(verts, 0.1, 0.0, filament_map, default_filament=1)
        depth = _tree_depth(node)
        assert depth <= 12
        leaves = _collect_leaves(node)
        assert all(l in (1, 2) for l in leaves)

    def test_max_depth_zero_returns_leaf(self):
        """max_depth=0 forces centroid fallback → single LeafNode."""
        verts = np.array([
            [0, 0, 0.0],
            [1, 0, 0.0],
            [0.5, 0.5, 0.5],
        ], dtype=np.float64)
        filament_map = {0: 1, 1: 2, 2: 3, 3: 4, 4: 5}
        node = subdivide_triangle(
            verts, 0.1, 0.0, filament_map, default_filament=1, max_depth=0,
        )
        assert isinstance(node, LeafNode)

    def test_default_filament_used_for_unknown_layer(self):
        """Layer not in filament_map → default_filament is used."""
        verts = np.array([
            [0, 0, 0.01],
            [1, 0, 0.02],
            [0, 1, 0.03],
        ], dtype=np.float64)
        node = subdivide_triangle(
            verts, 0.1, 0.0, filament_by_layer={}, default_filament=5,
        )
        assert isinstance(node, LeafNode)
        assert node.state == 5

    def test_encode_roundtrip_multi_layer(self):
        """Encode/decode round-trip for multi-layer tree."""
        verts = np.array([
            [0, 0, 0.0],
            [1, 0, 0.0],
            [0.5, 0.5, 0.35],
        ], dtype=np.float64)
        filament_map = {0: 1, 1: 2, 2: 3, 3: 4}
        node = subdivide_triangle(verts, 0.1, 0.0, filament_map, default_filament=1)
        hex_str = encode_bisection_tree(node)
        decoded = decode_bisection_tree(hex_str)
        assert decoded == node

    def test_negative_z_handled(self):
        """Triangle below z=0 still works: global_z_min shifts everything."""
        verts = np.array([
            [0, 0, -0.05],
            [1, 0, -0.05],
            [0.5, 0.5, 0.05],
        ], dtype=np.float64)
        filament_map = {0: 1, 1: 2}
        node = subdivide_triangle(
            verts, 0.1, global_z_min=-0.05, filament_by_layer=filament_map,
            default_filament=1,
        )
        leaves = _collect_leaves(node)
        assert all(l in (1, 2) for l in leaves)

    def test_split_node_has_valid_edges(self):
        """All SplitNodes in the resulting tree have valid special_side values."""
        verts = np.array([
            [0, 0, 0.0],
            [1, 0, 0.0],
            [0.5, 0.5, 0.25],
        ], dtype=np.float64)
        filament_map = {0: 1, 1: 2, 2: 3}
        node = subdivide_triangle(verts, 0.1, 0.0, filament_map, default_filament=1)

        def _check_edges(n):
            if isinstance(n, SplitNode):
                assert n.special_side in (0, 1, 2)
                assert n.split_sides in (2, 3), "Only 2-split and 3-split allowed"
                assert len(n.children) == n.split_sides + 1
                for c in n.children:
                    _check_edges(c)

        _check_edges(node)

    def test_no_1split_nodes(self):
        """AC-14: Bisection trees use only 2-split and 3-split nodes."""
        verts = np.array([
            [0, 0, 0.0],
            [1, 0, 0.0],
            [0.5, 0.5, 0.35],  # spans 4 layers
        ], dtype=np.float64)
        filament_map = {0: 1, 1: 2, 2: 1, 3: 2}
        node = subdivide_triangle(verts, 0.1, 0.0, filament_map, default_filament=1)

        def _check_no_1split(n):
            if isinstance(n, SplitNode):
                assert n.split_sides in (2, 3), (
                    f"Found 1-split node, expected only 2-split or 3-split"
                )
                for c in n.children:
                    _check_no_1split(c)

        _check_no_1split(node)

    def test_spatial_verification(self):
        """AC-13: Verify decoded sub-triangle centroids have correct filament for their layer."""
        # Triangle spanning 5 layers
        verts = np.array([
            [0, 0, 0.0],
            [1, 0, 0.0],
            [0.5, 0.5, 0.45],
        ], dtype=np.float64)
        layer_height = 0.1
        filament_map = {0: 1, 1: 2, 2: 1, 3: 2, 4: 1}
        node = subdivide_triangle(verts, layer_height, 0.0, filament_map, default_filament=1)

        # Walk tree to compute centroids per leaf
        def _verify(n, v0, v1, v2):
            """Recursively verify leaf assignments match layer expectations."""
            if isinstance(n, LeafNode):
                cz = (v0[2] + v1[2] + v2[2]) / 3.0
                layer = int(cz / layer_height)
                layer = max(0, layer)
                # Near layer boundaries, the subdivider may legitimately assign
                # the sub-triangle to either adjacent layer.
                boundary_tol = layer_height * 0.02
                frac = (cz / layer_height) - layer
                near_upper = frac > (1.0 - boundary_tol / layer_height)
                near_lower = frac < (boundary_tol / layer_height) and layer > 0
                allowed = {filament_map.get(layer, 1)}
                if near_upper:
                    allowed.add(filament_map.get(layer + 1, 1))
                if near_lower:
                    allowed.add(filament_map.get(layer - 1, 1))
                assert n.state in allowed, (
                    f"Leaf at centroid z={cz:.4f} (layer {layer}) has state {n.state}, "
                    f"expected one of {allowed}"
                )
                return

            assert isinstance(n, SplitNode)

            def _mid(a, b):
                return ((a[0]+b[0])*0.5, (a[1]+b[1])*0.5, (a[2]+b[2])*0.5)

            if n.split_sides == 3:
                # 3-split: all edges bisected
                m01, m12, m20 = _mid(v0, v1), _mid(v1, v2), _mid(v2, v0)
                _verify(n.children[0], v0, m01, m20)
                _verify(n.children[1], m01, v1, m12)
                _verify(n.children[2], m12, v2, m20)
                _verify(n.children[3], m01, m12, m20)
            elif n.split_sides == 2:
                s = n.special_side
                if s == 2:  # Bambu side 2: edge v0→v1 kept
                    m12, m20 = _mid(v1, v2), _mid(v2, v0)
                    _verify(n.children[0], v2, m20, m12)
                    _verify(n.children[1], m20, v0, m12)
                    _verify(n.children[2], v0, v1, m12)
                elif s == 0:  # Bambu side 0: edge v1→v2 kept
                    m01, m20 = _mid(v0, v1), _mid(v2, v0)
                    _verify(n.children[0], v0, m01, m20)
                    _verify(n.children[1], m01, v1, m20)
                    _verify(n.children[2], v1, v2, m20)
                else:  # s == 1, Bambu side 1: edge v2→v0 kept
                    m01, m12 = _mid(v0, v1), _mid(v1, v2)
                    _verify(n.children[0], v1, m12, m01)
                    _verify(n.children[1], m12, v2, m01)
                    _verify(n.children[2], v2, v0, m01)

        v0 = tuple(verts[0])
        v1 = tuple(verts[1])
        v2 = tuple(verts[2])
        _verify(node, v0, v1, v2)

    def test_fast_path_matches_tree_path(self):
        """_make_subdivider hex output matches subdivide_triangle → encode_bisection_tree."""
        from full_spectrum.subdivision import _make_subdivider, _face_to_hex

        verts = np.array([
            [0, 0, 0.0],
            [1, 0, 0.0],
            [0.5, 0.5, 0.35],
        ], dtype=np.float64)
        filament_map = {0: 1, 1: 2, 2: 1, 3: 2}
        max_depth = 12
        epsilon = 0.1 * 0.001

        # Tree path
        node = subdivide_triangle(verts, 0.1, 0.0, filament_map, default_filament=1, max_depth=max_depth)
        tree_hex = encode_bisection_tree(node)

        # Fast path
        sub_fn = _make_subdivider(0.1, 0.0, filament_map, 1, max_depth, epsilon)
        fast_hex = _face_to_hex(sub_fn, verts, max_depth)

        assert tree_hex == fast_hex


# ---------------------------------------------------------------------------
# encode_boundary_faces
# ---------------------------------------------------------------------------


class TestEncodeBoundaryFaces:
    def _make_mixed_mesh(self):
        """Mesh with 2 interior faces (flat) and 2 boundary faces (angled)."""
        vertices = np.array([
            # Interior face 0: flat at z=0.02
            [0, 0, 0.02], [1, 0, 0.02], [0.5, 1, 0.02],
            # Interior face 1: flat at z=0.12
            [0, 0, 0.12], [1, 0, 0.12], [0.5, 1, 0.12],
            # Boundary face 2: z spans 0.0 to 0.15
            [2, 0, 0.0], [3, 0, 0.0], [2.5, 1, 0.15],
            # Boundary face 3: z spans 0.05 to 0.25
            [4, 0, 0.05], [5, 0, 0.05], [4.5, 1, 0.25],
        ], dtype=np.float64)
        faces = np.array([
            [0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10, 11],
        ], dtype=np.int32)
        return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)

    def test_only_boundary_faces_in_result(self):
        """Result dict keys are only boundary face indices."""
        mesh = self._make_mixed_mesh()
        face_filaments = np.array([1, 2, 1, 2])
        result = encode_boundary_faces(mesh, face_filaments, layer_height=0.1)
        # Faces 0, 1 are interior; faces 2, 3 are boundary
        assert 0 not in result
        assert 1 not in result
        assert 2 in result
        assert 3 in result

    def test_hex_strings_decode_to_valid_trees(self):
        """All returned hex strings decode without error."""
        mesh = self._make_mixed_mesh()
        face_filaments = np.array([1, 2, 1, 2])
        result = encode_boundary_faces(mesh, face_filaments, layer_height=0.1)
        for face_idx, hex_str in result.items():
            tree = decode_bisection_tree(hex_str)
            leaves = _collect_leaves(tree)
            assert len(leaves) >= 1, f"Face {face_idx} tree has no leaves"

    def test_interior_only_mesh_returns_empty(self):
        """Completely flat mesh → no boundary faces → empty dict."""
        vertices = np.array([
            [0, 0, 0.01], [1, 0, 0.01], [0.5, 1, 0.01],
            [2, 0, 0.01], [3, 0, 0.01], [2.5, 1, 0.01],
        ], dtype=np.float64)
        faces = np.array([[0, 1, 2], [3, 4, 5]], dtype=np.int32)
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        face_filaments = np.array([1, 1])
        result = encode_boundary_faces(mesh, face_filaments, layer_height=0.1)
        assert result == {}

    def test_encode_roundtrip(self):
        """Encode → decode produces identical tree for each boundary face."""
        mesh = self._make_mixed_mesh()
        face_filaments = np.array([1, 2, 1, 2])
        result = encode_boundary_faces(mesh, face_filaments, layer_height=0.1)
        for hex_str in result.values():
            tree = decode_bisection_tree(hex_str)
            re_encoded = encode_bisection_tree(tree)
            assert re_encoded == hex_str
