"""Tests for boundary face detection and recursive bisection tree construction."""

from __future__ import annotations

import numpy as np
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
        from full_spectrum.mesh import LAYER_EPSILON_FACTOR
        epsilon = layer_height * LAYER_EPSILON_FACTOR  # 0.0001
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
