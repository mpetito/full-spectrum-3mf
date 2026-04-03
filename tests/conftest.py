"""Shared pytest fixtures for Full Spectrum tests."""

import json
import zipfile
from pathlib import Path

import numpy as np
import pytest
import trimesh
from click.testing import CliRunner
from lxml import etree

from full_spectrum.config import (
    ColorMapping,
    CyclicPalette,
    FullSpectrumConfig,
    GradientPalette,
    GradientStop,
)
from full_spectrum.threemf import NS_CORE, NS_SLIC3RPE


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def simple_cube_stl(tmp_path: Path) -> Path:
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
def painted_3mf(tmp_path: Path) -> Path:
    """Generate a 3MF with per-triangle slic3rpe:mmu_segmentation attributes."""
    verts = [
        (0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),
        (0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10),
    ]
    tris = [
        (0, 1, 2), (0, 2, 3),  # bottom
        (4, 6, 5), (4, 7, 6),  # top
        (0, 4, 5), (0, 5, 1),  # front
        (2, 6, 7), (2, 7, 3),  # back
        (0, 3, 7), (0, 7, 4),  # left
        (1, 5, 6), (1, 6, 2),  # right
    ]
    # Paint: bottom faces → filament 1 (default), top faces → filament 2
    face_colors = {2: "8", 3: "8"}  # top face pair → filament 2

    nsmap = {None: NS_CORE, "slic3rpe": NS_SLIC3RPE}
    root = etree.Element("model", nsmap=nsmap)
    root.set("unit", "millimeter")
    resources = etree.SubElement(root, "resources")
    obj = etree.SubElement(resources, "object", id="1", type="model")
    mesh_el = etree.SubElement(obj, "mesh")
    verts_el = etree.SubElement(mesh_el, "vertices")
    for x, y, z in verts:
        etree.SubElement(verts_el, "vertex", x=str(x), y=str(y), z=str(z))
    tris_el = etree.SubElement(mesh_el, "triangles")
    for i, (v1, v2, v3) in enumerate(tris):
        attrib = {"v1": str(v1), "v2": str(v2), "v3": str(v3)}
        if i in face_colors:
            attrib[f"{{{NS_SLIC3RPE}}}mmu_segmentation"] = face_colors[i]
        etree.SubElement(tris_el, "triangle", **attrib)
    build = etree.SubElement(root, "build")
    etree.SubElement(build, "item", objectid="1")

    model_bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    config_xml = b'<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <object id="1">\n    <metadata type="object" key="extruder" value="1"/>\n  </object>\n</config>'

    out = tmp_path / "painted.3mf"
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("_rels/.rels", "<Relationships/>")
        zf.writestr("3D/3dmodel.model", model_bytes)
        zf.writestr("Metadata/Slic3r_PE_model.config", config_xml)
    return out
