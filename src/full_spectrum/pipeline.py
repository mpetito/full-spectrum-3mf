"""Pipeline orchestration: wire all modules together."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh

from full_spectrum.config import (
    ColorMapping,
    CyclicPalette,
    FullSpectrumConfig,
    GradientPalette,
)
from full_spectrum.encoding import filament_to_hex
from full_spectrum.mesh import (
    compute_region_layers,
    LAYER_EPSILON_FACTOR,
    load_mesh,
    slice_faces_at_layers,
    cluster_faces_by_filament,
)
from full_spectrum.palette import apply_cyclic, apply_gradient, build_gradient_layer_map
from full_spectrum.subdivision import encode_boundary_faces
from full_spectrum.threemf import read_3mf, write_3mf

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of a Full Spectrum processing run."""
    success: bool
    face_count: int = 0
    layer_count: int = 0
    filament_distribution: dict[int, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    boundary_face_count: int = 0
    boundary_face_pct: float = 0.0


def _find_mapping(
    config: FullSpectrumConfig, input_filament: int
) -> ColorMapping | None:
    """Find color mapping for an input filament, or None."""
    for cm in config.color_mappings:
        if cm.input_filament == input_filament:
            return cm
    return None


def _default_cyclic_mapping() -> CyclicPalette:
    """Default palette when no mapping is configured."""
    return CyclicPalette(pattern=(1, 2))


def _build_layer_filament_map(
    mesh: trimesh.Trimesh,
    config: FullSpectrumConfig,
    clusters: dict[int, np.ndarray],
    default_filament: int,
    warnings: list[str],
) -> dict[int, int]:
    """Build a complete layer→filament map covering all layers from palette logic.

    Uses the same global_z_min reference as ``encode_boundary_faces`` so layer
    indices are consistent between the map and the subdivision code.

    Each cluster only writes its own occupied layers, so multi-filament
    inputs do not overwrite each other.
    """
    lh = config.layer_height_mm
    epsilon = lh * LAYER_EPSILON_FACTOR

    # global_z_min must match encode_boundary_faces (centroid-based)
    global_z_min = float(mesh.triangles_center[:, 2].min())
    vertex_z_max = float(mesh.vertices[:, 2].max())
    max_layer = max(0, int(np.floor((vertex_z_max - global_z_min + epsilon) / lh)))

    # Initialise every layer to default
    layer_map: dict[int, int] = {layer: default_filament for layer in range(max_layer + 1)}

    for input_fil, face_indices in clusters.items():
        mapping = _find_mapping(config, input_fil)
        if mapping is None:
            palette = _default_cyclic_mapping()
        else:
            palette = mapping.output_palette

        # Delegate layer computation to compute_region_layers
        layer_indices, region_layers = compute_region_layers(
            mesh, config.layer_height_mm, face_indices
        )

        # Offset between global and region-local layer indices
        region_centroids_z = mesh.triangles_center[face_indices, 2]
        region_z_min = float(region_centroids_z.min())
        region_offset = max(
            0, int(np.floor((region_z_min - global_z_min + epsilon) / lh))
        )

        # All global layers this cluster spans (not just centroid layers,
        # because boundary faces cross intermediate layers too)
        occupied_global = range(region_offset, region_offset + region_layers)

        if isinstance(palette, CyclicPalette):
            for gl in occupied_global:
                if gl > max_layer:
                    break
                layer_map[gl] = palette.pattern[(gl - region_offset) % len(palette.pattern)]

        elif isinstance(palette, GradientPalette):
            stops = [(s.t, s.filament) for s in palette.stops]
            # Build the full gradient layer map for this region
            gradient_map = build_gradient_layer_map(
                region_layers, stops
            )
            for gl in occupied_global:
                local_l = gl - region_offset
                if 0 <= local_l < region_layers:
                    layer_map[gl] = int(gradient_map[local_l])

    return layer_map


def process(
    input_path: str | Path,
    config: FullSpectrumConfig,
    output_path: str | Path,
    flatten: bool = False,
    dry_run: bool = False,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> PipelineResult:
    """Run the Full Spectrum pipeline: load → stratify → dither → write.

    Args:
        input_path: Path to input STL or 3MF file
        config: Palette configuration
        output_path: Path for output 3MF file
        flatten: Flatten sub-painted triangles to dominant filament
        dry_run: Validate without writing output
        progress_callback: Optional (stage, done, total) callback for progress

    Returns:
        PipelineResult with statistics and warnings
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    warnings: list[str] = []

    # Step 1: Load mesh geometry
    mesh = load_mesh(input_path)
    n_faces = len(mesh.faces)

    # Step 2: Read face colors (3MF only)
    face_colors: dict[int, int] = {}
    default_filament = 1

    if input_path.suffix.lower() == ".3mf":
        data_3mf = read_3mf(input_path, flatten=flatten)
        face_colors = data_3mf.face_colors
        default_filament = data_3mf.default_filament

        # Validate face count consistency between trimesh and 3MF parser
        if len(data_3mf.faces) != n_faces:
            raise ValueError(
                f"Face count mismatch: trimesh loaded {n_faces} faces but "
                f"3MF parser found {len(data_3mf.faces)}. "
                "The 3MF may contain multiple meshes/components with "
                "incompatible face ordering."
            )

    # Step 2b: Remesh at layer boundaries (geometry slicing strategy only)
    original_face_count = n_faces
    if config.boundary_split and config.boundary_strategy == "geometry":
        if progress_callback is not None:
            progress_callback("remesh", 0, 1)
        new_vertices, new_faces, parent_map = slice_faces_at_layers(
            mesh.vertices, mesh.faces, config.layer_height_mm,
        )
        # Remap face colors to the new face indices
        new_face_colors: dict[int, int] = {}
        for new_idx in range(len(new_faces)):
            parent_idx = int(parent_map[new_idx])
            if parent_idx in face_colors:
                new_face_colors[new_idx] = face_colors[parent_idx]
        face_colors = new_face_colors
        # Replace mesh with the remeshed version without trimesh processing,
        # which can merge/reindex geometry and invalidate parent_map-based
        # face color remapping.
        mesh = trimesh.Trimesh(
            vertices=new_vertices,
            faces=new_faces,
            process=False,
            validate=False,
        )
        n_faces = len(new_faces)
        if progress_callback is not None:
            progress_callback("remesh", 1, 1)

    # Step 3: Cluster faces by input filament
    clusters = cluster_faces_by_filament(face_colors, n_faces, default_filament)

    # Step 4: Apply palette to each cluster
    face_filaments = np.full(n_faces, default_filament, dtype=np.int32)
    total_layer_count = 0

    for input_fil, face_indices in clusters.items():
        mapping = _find_mapping(config, input_fil)

        if mapping is None:
            palette = _default_cyclic_mapping()
            warnings.append(
                f"No mapping for input filament {input_fil}; using default cyclic [1, 2]"
            )
        else:
            palette = mapping.output_palette

        # Compute region-local layers
        layer_indices, region_layers = compute_region_layers(
            mesh, config.layer_height_mm, face_indices
        )
        total_layer_count = max(total_layer_count, region_layers)

        # Apply palette
        if isinstance(palette, CyclicPalette):
            assigned = apply_cyclic(layer_indices, palette.pattern)
        elif isinstance(palette, GradientPalette):
            stops = [(s.t, s.filament) for s in palette.stops]
            assigned = apply_gradient(
                layer_indices, region_layers, stops
            )
        else:
            warnings.append(f"Unknown palette type for filament {input_fil}; skipping")
            continue

        face_filaments[face_indices] = assigned

    # Step 5: Compute distribution
    unique, counts = np.unique(face_filaments, return_counts=True)
    distribution = {int(u): int(c) for u, c in zip(unique, counts)}

    # Step 6: Convert to hex strings
    face_hex: list[str] = []
    for i in range(n_faces):
        fil = int(face_filaments[i])
        if fil == default_filament:
            face_hex.append("")
        else:
            face_hex.append(filament_to_hex(fil))

    # Step 6b: Bisection encoding for boundary faces
    boundary_face_count = 0
    if config.boundary_split and config.boundary_strategy == "bisection":
        def _boundary_progress(done: int, total: int) -> None:
            if progress_callback is not None:
                progress_callback("bisection", done, total)

        # Build a complete layer→filament map from the palette so that
        # subdivision can look up the correct filament for every layer,
        # not just the few layers that happen to contain face centroids.
        layer_filament_map = _build_layer_filament_map(
            mesh, config, clusters, default_filament, warnings,
        )

        boundary_hex = encode_boundary_faces(
            mesh,
            face_filaments,
            config.layer_height_mm,
            max_depth=config.max_split_depth,
            progress_callback=_boundary_progress if progress_callback else None,
            layer_filament_map=layer_filament_map,
        )
        # Merge: overwrite whole-face hex for boundary faces
        for face_idx, hex_str in boundary_hex.items():
            face_hex[face_idx] = hex_str
        boundary_face_count = len(boundary_hex)

    # Step 6c: Boundary face statistics (geometry strategy)
    if config.boundary_split and config.boundary_strategy == "geometry":
        boundary_face_count = n_faces - original_face_count

    boundary_face_pct = (
        boundary_face_count / n_faces * 100.0 if n_faces > 0 else 0.0
    )

    # Step 7: Write output
    if not dry_run:
        write_3mf(
            output_path,
            mesh.vertices,
            mesh.faces,
            face_hex,
            default_filament=default_filament,
            target_format=config.target_format,
        )

    return PipelineResult(
        success=True,
        face_count=n_faces,
        layer_count=total_layer_count,
        filament_distribution=distribution,
        warnings=warnings,
        boundary_face_count=boundary_face_count,
        boundary_face_pct=boundary_face_pct,
    )
