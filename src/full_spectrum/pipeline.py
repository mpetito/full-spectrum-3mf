"""Pipeline orchestration: wire all modules together."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from full_spectrum.config import (
    ColorMapping,
    CyclicPalette,
    FullSpectrumConfig,
    GradientPalette,
)
from full_spectrum.mesh import (
    cluster_faces_by_filament,
    compute_region_layers,
    load_mesh,
)
from full_spectrum.palette import apply_cyclic, apply_gradient
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
    return CyclicPalette(pattern=[1, 2])


def process(
    input_path: str | Path,
    config: FullSpectrumConfig,
    output_path: str | Path,
    flatten: bool = False,
    dry_run: bool = False,
) -> PipelineResult:
    """Run the Full Spectrum pipeline: load → stratify → dither → write.

    Args:
        input_path: Path to input STL or 3MF file
        config: Palette configuration
        output_path: Path for output 3MF file
        flatten: Flatten sub-painted triangles to dominant filament
        dry_run: Validate without writing output

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
                layer_indices, region_layers, stops, palette.max_period
            )
        else:
            warnings.append(f"Unknown palette type for filament {input_fil}; skipping")
            continue

        face_filaments[face_indices] = assigned

    # Step 5: Compute distribution
    unique, counts = np.unique(face_filaments, return_counts=True)
    distribution = {int(u): int(c) for u, c in zip(unique, counts)}

    # Step 6: Write output
    if not dry_run:
        write_3mf(
            output_path,
            mesh.vertices,
            mesh.faces,
            face_filaments,
            default_filament=default_filament,
            target_format=config.target_format,
        )

    return PipelineResult(
        success=True,
        face_count=n_faces,
        layer_count=total_layer_count,
        filament_distribution=distribution,
        warnings=warnings,
    )
