"""Integration tests for the Full Spectrum pipeline."""

import time
import zipfile
from pathlib import Path

import numpy as np
import pytest
import trimesh
from lxml import etree

from full_spectrum.config import (
    ColorMapping,
    CyclicPalette,
    FullSpectrumConfig,
    GradientPalette,
    GradientStop,
    default_config,
)
from full_spectrum.pipeline import PipelineResult, process
from full_spectrum.threemf import NS_CORE, NS_SLIC3RPE


@pytest.fixture
def cube_stl(tmp_path: Path) -> Path:
    mesh = trimesh.creation.box(extents=[10, 10, 10])
    out = tmp_path / "cube.stl"
    mesh.export(str(out))
    return out


@pytest.fixture
def simple_config() -> FullSpectrumConfig:
    return FullSpectrumConfig(
        layer_height_mm=0.1,
        target_format="both",
        color_mappings=[
            ColorMapping(input_filament=1, output_palette=CyclicPalette(pattern=[1, 2]))
        ],
    )


@pytest.fixture
def gradient_config() -> FullSpectrumConfig:
    return FullSpectrumConfig(
        layer_height_mm=0.1,
        target_format="both",
        color_mappings=[
            ColorMapping(
                input_filament=1,
                output_palette=GradientPalette(
                    stops=[GradientStop(t=0.0, filament=1), GradientStop(t=1.0, filament=2)],
                ),
            )
        ],
    )


class TestPipelineSTL:
    def test_stl_cyclic(self, cube_stl: Path, simple_config: FullSpectrumConfig, tmp_path: Path) -> None:
        out = tmp_path / "out.3mf"
        result = process(cube_stl, simple_config, out)
        assert result.success
        assert result.face_count > 0
        assert result.layer_count > 0
        assert out.exists()
        # Valid ZIP
        with zipfile.ZipFile(out) as zf:
            assert "3D/3dmodel.model" in zf.namelist()

    def test_stl_gradient(self, cube_stl: Path, gradient_config: FullSpectrumConfig, tmp_path: Path) -> None:
        out = tmp_path / "out.3mf"
        result = process(cube_stl, gradient_config, out)
        assert result.success
        assert set(result.filament_distribution.keys()).issubset({1, 2})

    def test_default_palette(self, cube_stl: Path, tmp_path: Path) -> None:
        config = default_config(0.1)
        out = tmp_path / "out.3mf"
        result = process(cube_stl, config, out)
        assert result.success


class TestPipelineDryRun:
    def test_no_output_file(self, cube_stl: Path, simple_config: FullSpectrumConfig, tmp_path: Path) -> None:
        out = tmp_path / "should_not_exist.3mf"
        result = process(cube_stl, simple_config, out, dry_run=True)
        assert result.success
        assert not out.exists()


class TestPipelineStatistics:
    def test_result_fields(self, cube_stl: Path, simple_config: FullSpectrumConfig, tmp_path: Path) -> None:
        out = tmp_path / "out.3mf"
        result = process(cube_stl, simple_config, out)
        assert isinstance(result.face_count, int)
        assert result.face_count > 0
        assert isinstance(result.layer_count, int)
        assert isinstance(result.filament_distribution, dict)
        total_faces = sum(result.filament_distribution.values())
        assert total_faces == result.face_count


class TestPipelineUnmappedFilament:
    def test_warning_on_unmapped(self, cube_stl: Path, tmp_path: Path) -> None:
        # Config that maps filament 5 but cube uses filament 1
        config = FullSpectrumConfig(
            layer_height_mm=0.1,
            target_format="both",
            color_mappings=[
                ColorMapping(input_filament=5, output_palette=CyclicPalette(pattern=(3, 4)))
            ],
        )
        out = tmp_path / "out.3mf"
        result = process(cube_stl, config, out)
        assert result.success
        assert any("No mapping" in w for w in result.warnings)


class TestPipeline3MF:
    def test_3mf_with_colors(self, painted_3mf: Path, tmp_path: Path) -> None:
        """Process a pre-painted 3MF file."""
        config = FullSpectrumConfig(
            layer_height_mm=1.0,
            target_format="both",
            color_mappings=[
                ColorMapping(input_filament=1, output_palette=CyclicPalette(pattern=(1, 3))),
                ColorMapping(input_filament=2, output_palette=CyclicPalette(pattern=(2, 4))),
            ],
        )
        out = tmp_path / "repainted.3mf"
        result = process(painted_3mf, config, out)
        assert result.success
        assert out.exists()
        assert result.face_count == 12


class TestPipelinePerformance:
    def test_large_mesh(self, tmp_path: Path) -> None:
        """100k triangle mesh completes in <10s."""
        mesh = trimesh.creation.icosphere(subdivisions=5)
        big_mesh = trimesh.util.concatenate([mesh] * 6)
        stl = tmp_path / "large.stl"
        big_mesh.export(str(stl))

        config = FullSpectrumConfig(
            layer_height_mm=0.1,
            target_format="both",
            color_mappings=[
                ColorMapping(input_filament=1, output_palette=CyclicPalette(pattern=(1, 2)))
            ],
        )
        out = tmp_path / "large_out.3mf"
        start = time.perf_counter()
        result = process(stl, config, out)
        elapsed = time.perf_counter() - start

        assert result.success
        assert result.face_count >= 100_000
        assert elapsed < 10.0, f"Took {elapsed:.1f}s, expected <10s"


class TestPipelineBoundarySplit:
    def test_boundary_split_on(self, cube_stl: Path, tmp_path: Path) -> None:
        """Pipeline with boundary_split=True produces valid output."""
        config = FullSpectrumConfig(
            layer_height_mm=0.1,
            target_format="both",
            color_mappings=[
                ColorMapping(input_filament=1, output_palette=CyclicPalette(pattern=(1, 2)))
            ],
            boundary_split=True,
        )
        out = tmp_path / "out.3mf"
        result = process(cube_stl, config, out)
        assert result.success
        assert result.boundary_face_count >= 0
        assert out.exists()

    def test_boundary_split_off_identical(self, cube_stl: Path, tmp_path: Path) -> None:
        """Without boundary_split, result has zero boundary faces."""
        config = FullSpectrumConfig(
            layer_height_mm=0.1,
            target_format="both",
            color_mappings=[
                ColorMapping(input_filament=1, output_palette=CyclicPalette(pattern=(1, 2)))
            ],
            boundary_split=False,
        )
        out = tmp_path / "out.3mf"
        result = process(cube_stl, config, out)
        assert result.success
        assert result.boundary_face_count == 0
        assert result.boundary_face_pct == 0.0

    def test_boundary_split_has_boundary_faces(self, cube_stl: Path, tmp_path: Path) -> None:
        """A cube STL processed with boundary_split should have boundary faces."""
        config = FullSpectrumConfig(
            layer_height_mm=0.1,
            target_format="both",
            color_mappings=[
                ColorMapping(input_filament=1, output_palette=CyclicPalette(pattern=(1, 2)))
            ],
            boundary_split=True,
        )
        out = tmp_path / "out.3mf"
        result = process(cube_stl, config, out)
        assert result.success
        # A cube has side faces that span many layers — should have boundary faces
        assert result.boundary_face_count > 0
        assert result.boundary_face_pct > 0.0
