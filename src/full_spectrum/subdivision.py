"""Boundary face detection and recursive bisection tree construction."""

from __future__ import annotations

import math
import multiprocessing as mp
import os
from collections.abc import Callable

import numpy as np
import trimesh

from full_spectrum.encoding import (
    BisectionNode,
    LeafNode,
    SplitNode,
    encode_bisection_tree,
)
from full_spectrum.mesh import compute_face_layers

_HEX_CHARS = "0123456789ABCDEF"


def find_boundary_faces(
    mesh: trimesh.Trimesh,
    layer_indices: np.ndarray,
    layer_height: float,
    global_z_min: float,
) -> np.ndarray:
    """Identify faces whose vertex Z-span crosses their assigned layer band.

    Args:
        mesh: The mesh (needed for vertex Z coordinates)
        layer_indices: (F,) int array of 0-based layer indices (from centroid assignment)
        layer_height: Layer height in mm
        global_z_min: The minimum Z coordinate used for layer computation

    Returns:
        Boolean mask of shape (F,) — True for boundary faces
    """
    band_low = global_z_min + layer_indices * layer_height
    band_high = band_low + layer_height

    # Per-face vertex Z coordinates, shape (F, 3)
    face_verts_z = mesh.vertices[mesh.faces][:, :, 2]
    z_min_per_face = face_verts_z.min(axis=1)
    z_max_per_face = face_verts_z.max(axis=1)

    epsilon = layer_height * 0.001
    return (z_min_per_face < band_low - epsilon) | (z_max_per_face > band_high + epsilon)


# -- Pure-Python vertex type used in the recursive hot path ----------------
type Vert3 = tuple[float, float, float]


def subdivide_triangle(
    vertices: np.ndarray,
    layer_height: float,
    global_z_min: float,
    filament_by_layer: dict[int, int],
    default_filament: int,
    max_depth: int = 9,
    epsilon: float | None = None,
) -> BisectionNode:
    """Recursively subdivide a triangle until every leaf fits within one layer.

    Public entry point — converts numpy vertices to tuples and delegates to the
    pure-Python inner loop for performance.
    """
    if epsilon is None:
        epsilon = layer_height * 0.001
    v0 = (float(vertices[0, 0]), float(vertices[0, 1]), float(vertices[0, 2]))
    v1 = (float(vertices[1, 0]), float(vertices[1, 1]), float(vertices[1, 2]))
    v2 = (float(vertices[2, 0]), float(vertices[2, 1]), float(vertices[2, 2]))
    return _subdivide(
        v0, v1, v2, layer_height, global_z_min,
        filament_by_layer, default_filament, max_depth, epsilon,
    )


def _subdivide(
    v0: Vert3,
    v1: Vert3,
    v2: Vert3,
    layer_height: float,
    global_z_min: float,
    filament_by_layer: dict[int, int],
    default_filament: int,
    max_depth: int,
    epsilon: float,
) -> BisectionNode:
    """Pure-Python recursive subdivision using 1-split, 2-split and 3-split nodes."""
    z0, z1, z2 = v0[2], v1[2], v2[2]
    z_lo = min(z0, z1, z2)
    z_hi = max(z0, z1, z2)

    layer_lo = max(0, math.floor((z_lo - global_z_min + epsilon) / layer_height))
    layer_hi = max(0, math.floor((z_hi - global_z_min + epsilon) / layer_height))

    # Base case — triangle fits in one layer
    if layer_lo == layer_hi:
        return LeafNode(state=filament_by_layer.get(layer_lo, default_filament))

    # Base case — depth cap
    if max_depth <= 0:
        centroid_z = (z0 + z1 + z2) / 3.0
        centroid_layer = max(
            0, math.floor((centroid_z - global_z_min + epsilon) / layer_height)
        )
        return LeafNode(state=filament_by_layer.get(centroid_layer, default_filament))

    next_depth = max_depth - 1
    limit_sq = layer_height * layer_height

    # 3D edge length squared — used for split-type decision (3-split vs 2-split)
    len_sq_0 = (v1[0]-v0[0])**2 + (v1[1]-v0[1])**2 + (v1[2]-v0[2])**2
    len_sq_1 = (v2[0]-v1[0])**2 + (v2[1]-v1[1])**2 + (v2[2]-v1[2])**2
    len_sq_2 = (v0[0]-v2[0])**2 + (v0[1]-v2[1])**2 + (v0[2]-v2[2])**2

    long0 = len_sq_0 > limit_sq
    long1 = len_sq_1 > limit_sq
    long2 = len_sq_2 > limit_sq
    n_long = long0 + long1 + long2

    # Z-span squared — used for edge selection within 2-split (keep most horizontal)
    dz_sq_0 = (z1 - z0) ** 2  # edge 0: v0→v1
    dz_sq_1 = (z2 - z1) ** 2  # edge 1: v1→v2
    dz_sq_2 = (z0 - z2) ** 2  # edge 2: v2→v0

    def _mid(a: Vert3, b: Vert3) -> Vert3:
        return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5, (a[2] + b[2]) * 0.5)

    _rec = _subdivide  # local alias to avoid global lookup per call

    if n_long == 3:
        # 3-split: bisect all 3 edges, 4 children
        m01 = _mid(v0, v1)
        m12 = _mid(v1, v2)
        m20 = _mid(v2, v0)

        c0 = _rec(v0, m01, m20, layer_height, global_z_min, filament_by_layer, default_filament, next_depth, epsilon)
        c1 = _rec(m01, v1, m12, layer_height, global_z_min, filament_by_layer, default_filament, next_depth, epsilon)
        c2 = _rec(m12, v2, m20, layer_height, global_z_min, filament_by_layer, default_filament, next_depth, epsilon)
        c3 = _rec(m01, m12, m20, layer_height, global_z_min, filament_by_layer, default_filament, next_depth, epsilon)

        children = [c0, c1, c2, c3]
        if (
            isinstance(c0, LeafNode) and isinstance(c1, LeafNode)
            and isinstance(c2, LeafNode) and isinstance(c3, LeafNode)
            and c0.state == c1.state == c2.state == c3.state
        ):
            return c0
        return SplitNode(split_sides=3, special_side=0, children=children)

    if n_long >= 1:
        # 2-split: keep the most horizontal edge (smallest Z-span), bisect the other two
        # Bambu convention: special_side = kept side index, where
        # side 0 = v1→v2, side 1 = v2→v0, side 2 = v0→v1
        # Children: c0 = apex, c1 = middle, c2 = base (has kept edge)
        if dz_sq_0 <= dz_sq_1 and dz_sq_0 <= dz_sq_2:
            # Edge v0→v1 most horizontal → keep = Bambu side 2
            special_side = 2
            m12 = _mid(v1, v2)
            m20 = _mid(v2, v0)
            c0 = _rec(v2, m20, m12, layer_height, global_z_min, filament_by_layer, default_filament, next_depth, epsilon)
            c1 = _rec(m20, v0, m12, layer_height, global_z_min, filament_by_layer, default_filament, next_depth, epsilon)
            c2 = _rec(v0, v1, m12, layer_height, global_z_min, filament_by_layer, default_filament, next_depth, epsilon)
        elif dz_sq_1 <= dz_sq_2:
            # Edge v1→v2 most horizontal → keep = Bambu side 0
            special_side = 0
            m01 = _mid(v0, v1)
            m20 = _mid(v2, v0)
            c0 = _rec(v0, m01, m20, layer_height, global_z_min, filament_by_layer, default_filament, next_depth, epsilon)
            c1 = _rec(m01, v1, m20, layer_height, global_z_min, filament_by_layer, default_filament, next_depth, epsilon)
            c2 = _rec(v1, v2, m20, layer_height, global_z_min, filament_by_layer, default_filament, next_depth, epsilon)
        else:
            # Edge v2→v0 most horizontal → keep = Bambu side 1
            special_side = 1
            m01 = _mid(v0, v1)
            m12 = _mid(v1, v2)
            c0 = _rec(v1, m12, m01, layer_height, global_z_min, filament_by_layer, default_filament, next_depth, epsilon)
            c1 = _rec(m12, v2, m01, layer_height, global_z_min, filament_by_layer, default_filament, next_depth, epsilon)
            c2 = _rec(v2, v0, m01, layer_height, global_z_min, filament_by_layer, default_filament, next_depth, epsilon)

        if (
            isinstance(c0, LeafNode) and isinstance(c1, LeafNode) and isinstance(c2, LeafNode)
            and c0.state == c1.state == c2.state
        ):
            return c0
        return SplitNode(split_sides=2, special_side=special_side, children=[c0, c1, c2])

    # n_long == 0: no edges long enough to split, assign via centroid
    centroid_z = (z0 + z1 + z2) / 3.0
    centroid_layer = max(
        0, math.floor((centroid_z - global_z_min + epsilon) / layer_height)
    )
    return LeafNode(state=filament_by_layer.get(centroid_layer, default_filament))


# ---------------------------------------------------------------------------
# Fast path: produce hex string directly without intermediate tree objects.
# Uses closure to avoid passing constant args through every recursive call,
# and early z-span termination to limit recursion depth on near-horizontal faces.
# ---------------------------------------------------------------------------


def _make_subdivider(
    layer_height: float,
    global_z_min: float,
    filament_by_layer: dict[int, int],
    default_filament: int,
    max_depth: int,
    epsilon: float,
):
    """Return a closure that subdivides one face directly to hex string."""
    inv_lh = 1.0 / layer_height
    limit_sq = layer_height * layer_height
    _floor = math.floor

    def _subdivide(
        z0: float, z1: float, z2: float,
        v0: Vert3, v1: Vert3, v2: Vert3,
        depth: int,
        nibbles: list[int],
    ) -> int:
        """Subdivide and emit nibbles. Returns leaf state or -1 if split."""
        if z0 <= z1:
            if z0 <= z2:
                z_lo = z0
            else:
                z_lo = z2
        elif z1 <= z2:
            z_lo = z1
        else:
            z_lo = z2

        if z0 >= z1:
            if z0 >= z2:
                z_hi = z0
            else:
                z_hi = z2
        elif z1 >= z2:
            z_hi = z1
        else:
            z_hi = z2

        layer_lo_f = (z_lo - global_z_min + epsilon) * inv_lh
        layer_lo = 0 if layer_lo_f < 0 else int(_floor(layer_lo_f))
        layer_hi_f = (z_hi - global_z_min + epsilon) * inv_lh
        layer_hi = 0 if layer_hi_f < 0 else int(_floor(layer_hi_f))

        # Leaf: all vertices in same layer
        if layer_lo == layer_hi:
            state = filament_by_layer.get(layer_lo, default_filament)
            if state <= 2:
                nibbles.append(state << 2)
            else:
                nibbles.append(0xC)
                nibbles.append(state - 3)
            return state

        # Depth cap: assign based on centroid
        if depth <= 0:
            centroid_z = (z0 + z1 + z2) * 0.3333333333333333
            cl_f = (centroid_z - global_z_min + epsilon) * inv_lh
            cl = 0 if cl_f < 0 else int(_floor(cl_f))
            state = filament_by_layer.get(cl, default_filament)
            if state <= 2:
                nibbles.append(state << 2)
            else:
                nibbles.append(0xC)
                nibbles.append(state - 3)
            return state

        nd = depth - 1

        # 3D edge length squared — used for split-type decision (3-split vs 2-split)
        d0x = v1[0] - v0[0]; d0y = v1[1] - v0[1]; d0z = v1[2] - v0[2]
        d1x = v2[0] - v1[0]; d1y = v2[1] - v1[1]; d1z = v2[2] - v1[2]
        d2x = v0[0] - v2[0]; d2y = v0[1] - v2[1]; d2z = v0[2] - v2[2]
        len_sq_0 = d0x*d0x + d0y*d0y + d0z*d0z
        len_sq_1 = d1x*d1x + d1y*d1y + d1z*d1z
        len_sq_2 = d2x*d2x + d2y*d2y + d2z*d2z

        long0 = len_sq_0 > limit_sq
        long1 = len_sq_1 > limit_sq
        long2 = len_sq_2 > limit_sq
        n_long = long0 + long1 + long2

        # Z-span squared — used for edge selection within 2-split (keep most horizontal)
        dz_sq_0 = d0z * d0z  # edge 0: v0→v1
        dz_sq_1 = d1z * d1z  # edge 1: v1→v2
        dz_sq_2 = d2z * d2z  # edge 2: v2→v0

        if n_long == 3:
            # 3-split: bisect all 3 edges, 4 children
            m01z = (z0 + z1) * 0.5
            m12z = (z1 + z2) * 0.5
            m20z = (z2 + z0) * 0.5
            m01 = ((v0[0] + v1[0]) * 0.5, (v0[1] + v1[1]) * 0.5, m01z)
            m12 = ((v1[0] + v2[0]) * 0.5, (v1[1] + v2[1]) * 0.5, m12z)
            m20 = ((v2[0] + v0[0]) * 0.5, (v2[1] + v0[1]) * 0.5, m20z)

            # Reserve slot for split nibble
            split_pos = len(nibbles)
            nibbles.append(0)

            # DFS children in reverse index order: c3, c2, c1, c0
            s3 = _subdivide(m01z, m12z, m20z, m01, m12, m20, nd, nibbles)
            s2 = _subdivide(m12z, z2, m20z, m12, v2, m20, nd, nibbles)
            s1 = _subdivide(m01z, z1, m12z, m01, v1, m12, nd, nibbles)
            s0 = _subdivide(z0, m01z, m20z, v0, m01, m20, nd, nibbles)

            # Collapse if all children are identical leaves
            if s0 >= 0 and s0 == s1 and s1 == s2 and s2 == s3:
                del nibbles[split_pos:]
                if s0 <= 2:
                    nibbles.append(s0 << 2)
                else:
                    nibbles.append(0xC)
                    nibbles.append(s0 - 3)
                return s0

            nibbles[split_pos] = 3  # (0 << 2) | 3
            return -1

        if n_long >= 1:
            # 2-split: keep the most horizontal edge (smallest Z-span), bisect the other two
            # Bambu convention: special_side = kept side index, where
            # side 0 = v1→v2, side 1 = v2→v0, side 2 = v0→v1
            # Children: c0 = apex, c1 = middle, c2 = base (has kept edge)
            # Emitted in reverse: c2, c1, c0

            # Reserve slot for split nibble
            split_pos = len(nibbles)
            nibbles.append(0)

            if dz_sq_0 <= dz_sq_1 and dz_sq_0 <= dz_sq_2:
                # Edge v0→v1 most horizontal → keep = Bambu side 2
                special_side = 2
                m12z = (z1 + z2) * 0.5
                m20z = (z2 + z0) * 0.5
                m12 = ((v1[0] + v2[0]) * 0.5, (v1[1] + v2[1]) * 0.5, m12z)
                m20 = ((v2[0] + v0[0]) * 0.5, (v2[1] + v0[1]) * 0.5, m20z)
                # Reverse: c2 (base), c1 (middle), c0 (apex)
                s2 = _subdivide(z0, z1, m12z, v0, v1, m12, nd, nibbles)
                s1 = _subdivide(m20z, z0, m12z, m20, v0, m12, nd, nibbles)
                s0 = _subdivide(z2, m20z, m12z, v2, m20, m12, nd, nibbles)

            elif dz_sq_1 <= dz_sq_2:
                # Edge v1→v2 most horizontal → keep = Bambu side 0
                special_side = 0
                m01z = (z0 + z1) * 0.5
                m20z = (z2 + z0) * 0.5
                m01 = ((v0[0] + v1[0]) * 0.5, (v0[1] + v1[1]) * 0.5, m01z)
                m20 = ((v2[0] + v0[0]) * 0.5, (v2[1] + v0[1]) * 0.5, m20z)
                # Reverse: c2 (base), c1 (middle), c0 (apex)
                s2 = _subdivide(z1, z2, m20z, v1, v2, m20, nd, nibbles)
                s1 = _subdivide(m01z, z1, m20z, m01, v1, m20, nd, nibbles)
                s0 = _subdivide(z0, m01z, m20z, v0, m01, m20, nd, nibbles)

            else:
                # Edge v2→v0 most horizontal → keep = Bambu side 1
                special_side = 1
                m01z = (z0 + z1) * 0.5
                m12z = (z1 + z2) * 0.5
                m01 = ((v0[0] + v1[0]) * 0.5, (v0[1] + v1[1]) * 0.5, m01z)
                m12 = ((v1[0] + v2[0]) * 0.5, (v1[1] + v2[1]) * 0.5, m12z)
                # Reverse: c2 (base), c1 (middle), c0 (apex)
                s2 = _subdivide(z2, z0, m01z, v2, v0, m01, nd, nibbles)
                s1 = _subdivide(m12z, z2, m01z, m12, v2, m01, nd, nibbles)
                s0 = _subdivide(z1, m12z, m01z, v1, m12, m01, nd, nibbles)

            # Collapse if all children are identical leaves
            if s0 >= 0 and s0 == s1 and s1 == s2:
                del nibbles[split_pos:]
                if s0 <= 2:
                    nibbles.append(s0 << 2)
                else:
                    nibbles.append(0xC)
                    nibbles.append(s0 - 3)
                return s0

            nibbles[split_pos] = (special_side << 2) | 2
            return -1

        # n_long == 0: no edges long enough to split, assign via centroid
        centroid_z = (z0 + z1 + z2) * 0.3333333333333333
        cl_f = (centroid_z - global_z_min + epsilon) * inv_lh
        cl = 0 if cl_f < 0 else int(_floor(cl_f))
        state = filament_by_layer.get(cl, default_filament)
        if state <= 2:
            nibbles.append(state << 2)
        else:
            nibbles.append(0xC)
            nibbles.append(state - 3)
        return state

    return _subdivide


def _face_to_hex(
    subdivide_fn,
    fv: np.ndarray,
    max_depth: int,
) -> str:
    """Subdivide one face directly to a hex string (zero intermediate tree objects)."""
    v0: Vert3 = (float(fv[0, 0]), float(fv[0, 1]), float(fv[0, 2]))
    v1: Vert3 = (float(fv[1, 0]), float(fv[1, 1]), float(fv[1, 2]))
    v2: Vert3 = (float(fv[2, 0]), float(fv[2, 1]), float(fv[2, 2]))

    nibbles: list[int] = []
    subdivide_fn(v0[2], v1[2], v2[2], v0, v1, v2, max_depth, nibbles)
    # Reverse nibbles → hex chars → join
    return "".join(_HEX_CHARS[n] for n in reversed(nibbles))


# ---------------------------------------------------------------------------
# Multiprocessing support for encode_boundary_faces
# ---------------------------------------------------------------------------

# Global state for worker processes (initialised by _init_worker)
_worker_state: dict = {}


def _init_worker(
    shared_buf: mp.RawArray,
    shape: tuple[int, int, int],
    layer_height: float,
    global_z_min: float,
    filament_by_layer: dict[int, int],
    default_filament: int,
    max_depth: int,
    epsilon: float,
) -> None:
    """Initialise per-worker state: wrap shared memory and build subdivider closure."""
    _worker_state["verts"] = np.frombuffer(shared_buf, dtype=np.float64).reshape(shape)
    _worker_state["sub"] = _make_subdivider(
        layer_height, global_z_min,
        filament_by_layer, default_filament, max_depth, epsilon,
    )
    _worker_state["depth"] = max_depth


def _worker_encode_chunk(indices: list[int]) -> list[tuple[int, str]]:
    """Encode a chunk of face indices. Returns list of (face_index, hex_string)."""
    verts = _worker_state["verts"]
    sub_fn = _worker_state["sub"]
    depth = _worker_state["depth"]
    results = []
    for i in indices:
        results.append((i, _face_to_hex(sub_fn, verts[i], depth)))
    return results


def encode_boundary_faces(
    mesh: trimesh.Trimesh,
    face_filaments: np.ndarray,
    layer_height: float,
    max_depth: int = 9,
    progress_callback: Callable[[int, int], None] | None = None,
    layer_filament_map: dict[int, int] | None = None,
) -> dict[int, str]:
    """Compute bisection tree hex strings for boundary faces.

    Args:
        mesh: The mesh
        face_filaments: (F,) int array of 1-based filament assignments (from palette step)
        layer_height: Layer height in mm
        max_depth: Safety cap on recursion depth
        progress_callback: Optional (done, total) callback for progress reporting
        layer_filament_map: Pre-built layer→filament dict covering all layers.
            If None, inferred from face_filaments (centroid-based, may miss layers).

    Returns:
        Dict mapping face_index -> hex_string for boundary faces only.
        Interior faces are NOT included in this dict.
    """
    global_z_min = float(mesh.triangles_center[:, 2].min())
    layer_indices = compute_face_layers(mesh, layer_height)

    if layer_filament_map is None:
        # Build layer -> filament map (mode per layer)
        layer_filament_map_: dict[int, int] = {}
        for layer_idx in np.unique(layer_indices):
            mask = layer_indices == layer_idx
            filaments_in_layer = face_filaments[mask]
            values, counts = np.unique(filaments_in_layer, return_counts=True)
            layer_filament_map_[int(layer_idx)] = int(values[counts.argmax()])
        layer_filament_map = layer_filament_map_

    # Default filament = overall mode
    all_values, all_counts = np.unique(face_filaments, return_counts=True)
    default_filament = int(all_values[all_counts.argmax()])

    boundary_mask = find_boundary_faces(mesh, layer_indices, layer_height, global_z_min)
    boundary_indices = np.nonzero(boundary_mask)[0]
    n_boundary = len(boundary_indices)

    epsilon = layer_height * 0.001

    # Pre-fetch all face vertex coords into shared memory for multiprocessing
    all_face_verts = mesh.vertices[mesh.faces].astype(np.float64)  # (F, 3, 3)

    n_workers = os.cpu_count() or 1
    use_parallel = n_boundary > 100 and n_workers > 1

    if use_parallel:
        return _encode_parallel(
            all_face_verts, boundary_indices, n_boundary,
            layer_height, global_z_min, layer_filament_map,
            default_filament, max_depth, epsilon,
            n_workers, progress_callback,
        )
    else:
        return _encode_serial(
            all_face_verts, boundary_indices, n_boundary,
            layer_height, global_z_min, layer_filament_map,
            default_filament, max_depth, epsilon,
            progress_callback,
        )


def _encode_serial(
    all_face_verts: np.ndarray,
    boundary_indices: np.ndarray,
    n_boundary: int,
    layer_height: float,
    global_z_min: float,
    layer_filament_map: dict[int, int],
    default_filament: int,
    max_depth: int,
    epsilon: float,
    progress_callback: Callable[[int, int], None] | None,
) -> dict[int, str]:
    """Single-process encoding path."""
    subdivide_fn = _make_subdivider(
        layer_height, global_z_min,
        layer_filament_map, default_filament, max_depth, epsilon,
    )
    result: dict[int, str] = {}
    for done, i in enumerate(boundary_indices):
        result[int(i)] = _face_to_hex(subdivide_fn, all_face_verts[i], max_depth)
        if progress_callback is not None and (done & 0xFFF) == 0:
            progress_callback(done, n_boundary)
    if progress_callback is not None:
        progress_callback(n_boundary, n_boundary)
    return result


def _encode_parallel(
    all_face_verts: np.ndarray,
    boundary_indices: np.ndarray,
    n_boundary: int,
    layer_height: float,
    global_z_min: float,
    layer_filament_map: dict[int, int],
    default_filament: int,
    max_depth: int,
    epsilon: float,
    n_workers: int,
    progress_callback: Callable[[int, int], None] | None,
) -> dict[int, str]:
    """Multi-process encoding path using shared memory."""
    # Copy vertex data into a shared RawArray (avoids per-worker pickle cost)
    flat = all_face_verts.ravel()
    shared_buf = mp.RawArray("d", len(flat))
    np.frombuffer(shared_buf, dtype=np.float64)[:] = flat

    # Split boundary indices into chunks for imap – keep chunks small enough
    # so that every worker stays busy (at least 4× as many chunks as workers).
    chunk_size = max(4, n_boundary // (n_workers * 4))
    idx_list = boundary_indices.tolist()
    chunks = [idx_list[i : i + chunk_size] for i in range(0, len(idx_list), chunk_size)]

    result: dict[int, str] = {}
    done = 0

    with mp.Pool(
        n_workers,
        initializer=_init_worker,
        initargs=(
            shared_buf, all_face_verts.shape,
            layer_height, global_z_min,
            layer_filament_map, default_filament,
            max_depth, epsilon,
        ),
    ) as pool:
        for chunk_result in pool.imap_unordered(_worker_encode_chunk, chunks):
            for face_idx, hex_str in chunk_result:
                result[face_idx] = hex_str
            done += len(chunk_result)
            if progress_callback is not None:
                progress_callback(done, n_boundary)

    return result
