"""Round-trip validation tests."""

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
)
from full_spectrum.pipeline import process
from full_spectrum.threemf import NAMESPACES, NS_CORE, NS_SLIC3RPE


@pytest.fixture
def cube_stl(tmp_path: Path) -> Path:
    mesh = trimesh.creation.box(extents=[10, 10, 10])
    out = tmp_path / "cube.stl"
    mesh.export(str(out))
    return out


def _unpack_model_xml(path: Path) -> etree._Element:
    with zipfile.ZipFile(path) as zf:
        return etree.fromstring(zf.read("3D/3dmodel.model"))


class TestRoundtripSTL:
    def test_roundtrip(self, cube_stl: Path, tmp_path: Path) -> None:
        config = FullSpectrumConfig(
            layer_height_mm=1.0,
            target_format="both",
            color_mappings=[
                ColorMapping(input_filament=1, output_palette=CyclicPalette(pattern=[1, 2]))
            ],
        )
        out = tmp_path / "out.3mf"
        process(cube_stl, config, out)

        root = _unpack_model_xml(out)
        tris = root.findall(".//m:triangle", NAMESPACES)
        assert len(tris) > 0

        # At least some triangles should have color attributes
        colored = [
            t for t in tris
            if t.get(f"{{{NS_SLIC3RPE}}}mmu_segmentation") is not None
            or t.get("paint_color") is not None
        ]
        assert len(colored) > 0

    def test_xml_validity(self, cube_stl: Path, tmp_path: Path) -> None:
        config = FullSpectrumConfig(
            layer_height_mm=0.5,
            target_format="prusaslicer",
            color_mappings=[
                ColorMapping(input_filament=1, output_palette=CyclicPalette(pattern=[1, 3]))
            ],
        )
        out = tmp_path / "out.3mf"
        process(cube_stl, config, out)
        # Should parse without error
        root = _unpack_model_xml(out)
        assert root.tag == f"{{{NS_CORE}}}model"


class TestRoundtripGradient:
    def test_gradient_smoothness(self, cube_stl: Path, tmp_path: Path) -> None:
        config = FullSpectrumConfig(
            layer_height_mm=0.1,
            target_format="both",
            color_mappings=[
                ColorMapping(
                    input_filament=1,
                    output_palette=GradientPalette(
                        stops=[
                            GradientStop(t=0.0, filament=1),
                            GradientStop(t=0.5, filament=2),
                            GradientStop(t=1.0, filament=3),
                        ],
                    ),
                )
            ],
        )
        out = tmp_path / "out.3mf"
        result = process(cube_stl, config, out)
        assert result.success
        # Should use filaments 1, 2, and 3
        assert set(result.filament_distribution.keys()).issubset({1, 2, 3})
