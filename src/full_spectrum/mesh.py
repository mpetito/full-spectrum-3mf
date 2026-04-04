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
    Uses epsilon = 0.1% of layer_height for floating-point tolerance.
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


def slice_faces_at_layers(
    vertices: np.ndarray,
    faces: np.ndarray,
    layer_height: float,
    global_z_min: float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Slice mesh faces at horizontal layer boundaries.

    Clips faces that cross layer boundaries into sub-faces, each spanning
    at most one layer. Faces already within a single layer are kept unchanged.

    Args:
        vertices: (V, 3) float array of vertex coordinates
        faces: (F, 3) int array of vertex indices per triangle
        layer_height: Layer height in mm
        global_z_min: Z origin for layer computation. If None, uses min centroid Z.

    Returns:
        (new_vertices, new_faces, parent_map) where:
        - new_vertices: (V', 3) float array (V' >= V)
        - new_faces: (F', 3) int array (F' >= F)
        - parent_map: (F',) int array mapping each new face to its original face index
    """
    eps = layer_height * 0.001

    if global_z_min is None:
        centroids_z = vertices[faces].mean(axis=1)[:, 2]
        global_z_min = float(centroids_z.min())

    # Start with a copy of all original vertices
    new_verts_list: list[np.ndarray] = [vertices.copy()]
    total_v = len(vertices)
    out_faces: list[tuple[int, int, int]] = []
    out_parent: list[int] = []

    # Cache for deduplicating intersection vertices
    vert_cache: dict[tuple[float, float, float], int] = {}

    def _add_vertex(pt: np.ndarray) -> int:
        nonlocal total_v
        key = (round(pt[0], 9), round(pt[1], 9), round(pt[2], 9))
        if key in vert_cache:
            return vert_cache[key]
        idx = total_v
        new_verts_list.append(pt.reshape(1, 3))
        vert_cache[key] = idx
        total_v += 1
        return idx

    def _vertex_layer(z: float) -> int:
        return int(np.floor((z - global_z_min + eps) / layer_height))

    def _clip_polygon_z(poly: list[np.ndarray], z_cut: float, keep_below: bool) -> list[np.ndarray]:
        """Sutherland-Hodgman clip of convex polygon against z=z_cut plane.

        keep_below=True:  keep side where z <= z_cut + eps
        keep_below=False: keep side where z >= z_cut - eps
        """
        if not poly:
            return poly
        out: list[np.ndarray] = []
        n = len(poly)
        for i in range(n):
            cur = poly[i]
            nxt = poly[(i + 1) % n]
            if keep_below:
                cur_in = cur[2] <= z_cut + eps
                nxt_in = nxt[2] <= z_cut + eps
            else:
                cur_in = cur[2] >= z_cut - eps
                nxt_in = nxt[2] >= z_cut - eps

            if cur_in:
                out.append(cur)
                if not nxt_in:
                    # Edge exits — compute intersection
                    dz = nxt[2] - cur[2]
                    if abs(dz) > 1e-15:
                        t = (z_cut - cur[2]) / dz
                        out.append(cur + t * (nxt - cur))
            elif nxt_in:
                # Edge enters — compute intersection
                dz = nxt[2] - cur[2]
                if abs(dz) > 1e-15:
                    t = (z_cut - cur[2]) / dz
                    out.append(cur + t * (nxt - cur))
        return out

    def _emit_polygon(poly: list[np.ndarray], parent_idx: int) -> None:
        """Fan-triangulate a convex polygon and emit faces."""
        if len(poly) < 3:
            return
        i0 = _add_vertex(poly[0])
        prev = _add_vertex(poly[1])
        for k in range(2, len(poly)):
            cur = _add_vertex(poly[k])
            out_faces.append((i0, prev, cur))
            out_parent.append(parent_idx)
            prev = cur

    for fi in range(len(faces)):
        tri_indices = faces[fi]
        tri_verts = vertices[tri_indices]
        zs = tri_verts[:, 2]
        z_lo, z_hi = float(zs.min()), float(zs.max())

        layer_lo = _vertex_layer(z_lo)
        layer_hi = _vertex_layer(z_hi)

        if layer_lo == layer_hi:
            # Face within one layer — keep unchanged
            out_faces.append((int(tri_indices[0]), int(tri_indices[1]), int(tri_indices[2])))
            out_parent.append(fi)
            continue

        # Clip the original triangle to each layer slab directly (O(N), no recursion)
        tri_poly = [tri_verts[0].copy(), tri_verts[1].copy(), tri_verts[2].copy()]
        for k in range(layer_lo, layer_hi + 1):
            z_slab_lo = global_z_min + k * layer_height
            z_slab_hi = global_z_min + (k + 1) * layer_height

            # Clip original triangle to slab [z_slab_lo, z_slab_hi]
            slab_poly = tri_poly  # start from original
            if k > layer_lo:
                slab_poly = _clip_polygon_z(slab_poly, z_slab_lo, keep_below=False)
            if k < layer_hi:
                slab_poly = _clip_polygon_z(slab_poly, z_slab_hi, keep_below=True)

            _emit_polygon(slab_poly, fi)

    # Assemble output arrays
    if len(new_verts_list) > 1:
        new_vertices = np.vstack(new_verts_list)
    else:
        new_vertices = new_verts_list[0]
    new_faces = np.array(out_faces, dtype=np.int64).reshape(-1, 3)
    parent_map = np.array(out_parent, dtype=np.int64)

    return new_vertices, new_faces, parent_map


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
