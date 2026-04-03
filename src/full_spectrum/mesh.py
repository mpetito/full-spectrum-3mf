"""Mesh loading, centroid computation, and layer assignment."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh


class MeshError(Exception):
    """Raised for mesh loading or processing errors."""


def load_mesh(path: str | Path) -> trimesh.Trimesh:
    """Load a mesh from STL, 3MF, or OBJ file.
    
    Returns a single Trimesh object. Raises MeshError if the file
    cannot be loaded or contains no triangles.
    """
    path = Path(path)
    try:
        result = trimesh.load(str(path))
    except Exception as e:
        raise MeshError(f"Cannot load mesh from {path}: {e}") from e

    # trimesh.load may return a Scene for multi-mesh files
    if isinstance(result, trimesh.Scene):
        meshes = [g for g in result.geometry.values() if isinstance(g, trimesh.Trimesh)]
        if not meshes:
            raise MeshError(f"No triangle meshes found in {path}")
        # Concatenate all meshes into one
        result = trimesh.util.concatenate(meshes)

    if not isinstance(result, trimesh.Trimesh):
        raise MeshError(f"Unexpected mesh type from {path}: {type(result).__name__}")

    if len(result.faces) == 0:
        raise MeshError(f"Mesh from {path} contains no triangles")

    return result


def compute_face_layers(mesh: trimesh.Trimesh, layer_height: float) -> np.ndarray:
    """Assign each face to a Z-layer based on its centroid Z coordinate.
    
    Returns an int array of shape (n_faces,) with 0-based layer indices.
    Uses epsilon = 1% of layer_height for floating-point tolerance.
    """
    centroids_z = mesh.triangles_center[:, 2]
    z_min = centroids_z.min()
    epsilon = layer_height * 0.001
    layer_indices = np.floor((centroids_z - z_min + epsilon) / layer_height).astype(int)
    return layer_indices


def compute_region_layers(
    mesh: trimesh.Trimesh,
    layer_height: float,
    face_indices: np.ndarray,
) -> tuple[np.ndarray, int]:
    """Compute layer indices for a subset of faces relative to their local Z range.
    
    Args:
        mesh: The full mesh
        layer_height: Layer height in mm
        face_indices: Indices of faces belonging to this region
    
    Returns:
        (layer_indices, total_layers) — layers are 0-based relative to region z_min
    """
    centroids_z = mesh.triangles_center[face_indices, 2]
    z_min = centroids_z.min()
    epsilon = layer_height * 0.001
    layer_indices = np.floor((centroids_z - z_min + epsilon) / layer_height).astype(int)
    total_layers = int(layer_indices.max()) + 1 if len(layer_indices) > 0 else 0
    return layer_indices, total_layers


def cluster_faces_by_filament(
    face_colors: dict[int, int],
    n_faces: int,
    default_filament: int = 1,
) -> dict[int, np.ndarray]:
    """Group face indices by their assigned filament.
    
    Faces not in face_colors are assigned the default_filament.
    Returns {filament: np.ndarray([face_idx, ...])}.
    """
    clusters: dict[int, list[int]] = {}
    for i in range(n_faces):
        filament = face_colors.get(i, default_filament)
        clusters.setdefault(filament, []).append(i)
    return {k: np.array(v, dtype=np.int64) for k, v in clusters.items()}
