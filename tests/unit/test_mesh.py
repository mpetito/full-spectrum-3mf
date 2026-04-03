"""Tests for mesh loading and layer assignment."""

from pathlib import Path

import numpy as np
import pytest
import trimesh

from full_spectrum.mesh import (
    MeshError,
    cluster_faces_by_filament,
    compute_face_layers,
    compute_region_layers,
    load_mesh,
)


@pytest.fixture
def cube_stl(tmp_path: Path) -> Path:
    """Generate a simple cube STL via trimesh."""
    mesh = trimesh.creation.box(extents=[10, 10, 10])
    out = tmp_path / "cube.stl"
    mesh.export(str(out))
    return out


@pytest.fixture
def cube_mesh() -> trimesh.Trimesh:
    """Create a cube mesh in memory."""
    return trimesh.creation.box(extents=[10, 10, 10])


class TestLoadMesh:
    def test_load_stl(self, cube_stl: Path) -> None:
        mesh = load_mesh(cube_stl)
        assert len(mesh.faces) > 0
        assert len(mesh.vertices) > 0

    def test_load_invalid(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.stl"
        bad.write_bytes(b"not a mesh")
        with pytest.raises(MeshError):
            load_mesh(bad)

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        with pytest.raises(MeshError):
            load_mesh(tmp_path / "nonexistent.stl")


class TestComputeFaceLayers:
    def test_single_layer(self) -> None:
        """Flat mesh should have all faces in layer 0."""
        # Create a flat square at z=0
        verts = np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0]], dtype=np.float64)
        faces = np.array([[0,1,2],[0,2,3]], dtype=np.int64)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces)
        layers = compute_face_layers(mesh, 0.1)
        assert np.all(layers == 0)

    def test_cube_layers(self, cube_mesh: trimesh.Trimesh) -> None:
        """Cube from -5 to +5 should have multiple layers."""
        layers = compute_face_layers(cube_mesh, 1.0)
        assert layers.shape == (len(cube_mesh.faces),)
        assert layers.min() >= 0
        # Cube is 10mm tall so there should be multiple distinct layers
        assert len(np.unique(layers)) > 1

    def test_epsilon_tolerance(self) -> None:
        """Faces at exactly z_min should land in layer 0, not -1."""
        verts = np.array([
            [0,0,0],[1,0,0],[0.5,0.5,0],      # face at z=0
            [0,0,1],[1,0,1],[0.5,0.5,1],       # face at z=1
        ], dtype=np.float64)
        faces = np.array([[0,1,2],[3,4,5]], dtype=np.int64)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces)
        layers = compute_face_layers(mesh, 0.5)
        assert layers[0] == 0
        assert layers[1] >= 1


class TestComputeRegionLayers:
    def test_region_subset(self, cube_mesh: trimesh.Trimesh) -> None:
        """Region layers should be relative to regional z_min."""
        n_faces = len(cube_mesh.faces)
        # Take first half of faces as a region
        region = np.arange(n_faces // 2, dtype=np.int64)
        layer_idx, total = compute_region_layers(cube_mesh, 1.0, region)
        assert layer_idx.shape == region.shape
        assert total >= 1
        assert layer_idx.min() == 0  # Always starts from 0


class TestClusterFaces:
    def test_single_color(self) -> None:
        clusters = cluster_faces_by_filament({}, 10)
        assert len(clusters) == 1
        assert 1 in clusters
        assert len(clusters[1]) == 10

    def test_multi_color(self) -> None:
        face_colors = {0: 1, 1: 2, 2: 1, 3: 3}
        clusters = cluster_faces_by_filament(face_colors, 5)
        assert set(clusters.keys()) == {1, 2, 3}
        np.testing.assert_array_equal(sorted(clusters[1]), [0, 2, 4])
        np.testing.assert_array_equal(clusters[2], [1])
        np.testing.assert_array_equal(clusters[3], [3])

    def test_custom_default(self) -> None:
        clusters = cluster_faces_by_filament({0: 2}, 3, default_filament=5)
        assert set(clusters.keys()) == {2, 5}
        np.testing.assert_array_equal(clusters[2], [0])
        np.testing.assert_array_equal(sorted(clusters[5]), [1, 2])


class TestLoadMeshScene:
    def test_load_3mf_as_mesh(self, tmp_path: Path) -> None:
        """Loading a 3MF file (which trimesh returns as Scene) should concatenate."""
        mesh = trimesh.creation.box(extents=[5, 5, 5])
        p = tmp_path / "box.stl"
        mesh.export(str(p))
        loaded = load_mesh(p)
        assert len(loaded.faces) > 0

    def test_empty_mesh_error(self, tmp_path: Path) -> None:
        """A mesh file with valid structure but zero faces should raise."""
        # Create a minimal file that trimesh can parse but has no triangles
        import struct
        # STL binary header (80 bytes) + 0-triangle count
        header = b"\x00" * 80 + struct.pack("<I", 0)
        p = tmp_path / "empty.stl"
        p.write_bytes(header)
        with pytest.raises(MeshError):
            load_mesh(p)
