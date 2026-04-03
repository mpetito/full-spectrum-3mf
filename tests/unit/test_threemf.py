"""Tests for 3MF reading and writing."""

from pathlib import Path
import zipfile

import numpy as np
import pytest
from lxml import etree

from full_spectrum.threemf import (
    NAMESPACES,
    NS_CORE,
    NS_SLIC3RPE,
    ThreeMFData,
    ThreeMFError,
    read_3mf,
    write_3mf,
)


def _make_cube_3mf(
    path: Path,
    color_attr: str = "slic3rpe",
    face_colors: dict[int, str] | None = None,
    default_filament: int = 1,
    multi_object: bool = False,
) -> Path:
    """Helper: generate a minimal 3MF with a cube and optional face colors."""
    verts = [
        (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
        (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
    ]
    tris = [
        (0, 1, 2), (0, 2, 3),  # bottom
        (4, 6, 5), (4, 7, 6),  # top
        (0, 4, 5), (0, 5, 1),  # front
        (2, 6, 7), (2, 7, 3),  # back
        (0, 3, 7), (0, 7, 4),  # left
        (1, 5, 6), (1, 6, 2),  # right
    ]

    nsmap = {None: NS_CORE, "slic3rpe": NS_SLIC3RPE}
    root = etree.Element("model", nsmap=nsmap)
    root.set("unit", "millimeter")

    resources = etree.SubElement(root, "resources")
    obj = etree.SubElement(resources, "object", id="1", type="model")
    if multi_object:
        etree.SubElement(resources, "object", id="2", type="model")

    mesh_el = etree.SubElement(obj, "mesh")
    verts_el = etree.SubElement(mesh_el, "vertices")
    for x, y, z in verts:
        etree.SubElement(verts_el, "vertex", x=str(x), y=str(y), z=str(z))

    tris_el = etree.SubElement(mesh_el, "triangles")
    if face_colors is None:
        face_colors = {}

    for i, (v1, v2, v3) in enumerate(tris):
        attrib = {"v1": str(v1), "v2": str(v2), "v3": str(v3)}
        if i in face_colors:
            if color_attr == "slic3rpe":
                attrib[f"{{{NS_SLIC3RPE}}}mmu_segmentation"] = face_colors[i]
            else:
                attrib["paint_color"] = face_colors[i]
        etree.SubElement(tris_el, "triangle", **attrib)

    build = etree.SubElement(root, "build")
    etree.SubElement(build, "item", objectid="1")

    model_bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)

    config_xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="1">
    <metadata type="object" key="extruder" value="{default_filament}"/>
  </object>
</config>""".encode("utf-8")

    out = path / "test.3mf"
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("_rels/.rels", "<Relationships/>")
        zf.writestr("3D/3dmodel.model", model_bytes)
        zf.writestr("Metadata/Slic3r_PE_model.config", config_xml)

    return out


class TestRead3MF:
    def test_valid_plain(self, tmp_path: Path) -> None:
        p = _make_cube_3mf(tmp_path)
        data = read_3mf(p)
        assert data.vertices.shape == (8, 3)
        assert data.faces.shape == (12, 3)
        assert data.face_colors == {}
        assert data.default_filament == 1

    def test_parse_colors_slic3rpe(self, tmp_path: Path) -> None:
        p = _make_cube_3mf(tmp_path, color_attr="slic3rpe",
                           face_colors={0: "4", 2: "8", 4: "0C"})
        data = read_3mf(p)
        assert data.face_colors == {0: 1, 2: 2, 4: 3}

    def test_parse_colors_paint_color(self, tmp_path: Path) -> None:
        p = _make_cube_3mf(tmp_path, color_attr="paint_color",
                           face_colors={1: "8", 3: "1C"})
        data = read_3mf(p)
        assert data.face_colors == {1: 2, 3: 4}

    def test_default_filament(self, tmp_path: Path) -> None:
        p = _make_cube_3mf(tmp_path, default_filament=3)
        data = read_3mf(p)
        assert data.default_filament == 3

    def test_invalid_zip(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.3mf"
        bad.write_bytes(b"not a zip")
        with pytest.raises(ThreeMFError, match="Cannot open"):
            read_3mf(bad)

    def test_multi_object_with_one_mesh(self, tmp_path: Path) -> None:
        """Multi-object 3MF where only one has a mesh should succeed."""
        p = _make_cube_3mf(tmp_path, multi_object=True)
        data = read_3mf(p)
        assert data.vertices.shape == (8, 3)
        assert data.faces.shape == (12, 3)

    def test_sub_painted_detection(self, tmp_path: Path) -> None:
        p = _make_cube_3mf(tmp_path, color_attr="slic3rpe",
                           face_colors={0: "0C1C2C"})
        with pytest.raises(ThreeMFError, match="Sub-painted"):
            read_3mf(p)

    def test_sub_painted_flatten(self, tmp_path: Path) -> None:
        p = _make_cube_3mf(tmp_path, color_attr="slic3rpe",
                           face_colors={0: "0C1C2C"})
        data = read_3mf(p, flatten=True)
        # "0C" → filament 3
        assert data.face_colors[0] == 3


class TestWrite3MF:
    def _write_and_read(
        self, tmp_path: Path, target_format: str = "both", **kwargs
    ) -> tuple[etree._Element, Path]:
        out = tmp_path / "out.3mf"
        verts = np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0]], dtype=np.float64)
        faces = np.array([[0,1,2],[0,2,3]], dtype=np.int32)
        filaments = np.array([1, 2], dtype=np.int32)
        write_3mf(out, verts, faces, filaments, target_format=target_format, **kwargs)
        assert out.exists()
        with zipfile.ZipFile(out, "r") as zf:
            model_xml = zf.read("3D/3dmodel.model")
        root = etree.fromstring(model_xml)
        return root, out

    def test_write_both(self, tmp_path: Path) -> None:
        root, _ = self._write_and_read(tmp_path, target_format="both")
        tris = root.findall(".//m:triangle", NAMESPACES)
        # Face 0: filament 1 (default) → no color attr
        assert tris[0].get(f"{{{NS_SLIC3RPE}}}mmu_segmentation") is None
        assert tris[0].get("paint_color") is None
        # Face 1: filament 2 → has both attrs
        assert tris[1].get(f"{{{NS_SLIC3RPE}}}mmu_segmentation") == "8"
        assert tris[1].get("paint_color") == "8"

    def test_write_prusaslicer(self, tmp_path: Path) -> None:
        root, _ = self._write_and_read(tmp_path, target_format="prusaslicer")
        tris = root.findall(".//m:triangle", NAMESPACES)
        assert tris[1].get(f"{{{NS_SLIC3RPE}}}mmu_segmentation") == "8"
        assert tris[1].get("paint_color") is None

    def test_write_bambu(self, tmp_path: Path) -> None:
        root, _ = self._write_and_read(tmp_path, target_format="bambu")
        tris = root.findall(".//m:triangle", NAMESPACES)
        assert tris[1].get("paint_color") == "8"
        # slic3rpe namespace should not be declared when not needed
        assert tris[1].get(f"{{{NS_SLIC3RPE}}}mmu_segmentation") is None

    def test_valid_zip_structure(self, tmp_path: Path) -> None:
        _, out = self._write_and_read(tmp_path)
        with zipfile.ZipFile(out, "r") as zf:
            names = set(zf.namelist())
            assert "[Content_Types].xml" in names
            assert "_rels/.rels" in names
            assert "3D/3dmodel.model" in names
            assert "Metadata/Slic3r_PE_model.config" in names

    def test_namespace_declaration(self, tmp_path: Path) -> None:
        root, _ = self._write_and_read(tmp_path, target_format="prusaslicer")
        # The slic3rpe namespace should be declared on root
        assert NS_SLIC3RPE in root.nsmap.values()

    def test_default_filament_in_config(self, tmp_path: Path) -> None:
        _, out = self._write_and_read(tmp_path, default_filament=3)
        with zipfile.ZipFile(out, "r") as zf:
            config = zf.read("Metadata/Slic3r_PE_model.config").decode()
        assert 'value="3"' in config


class TestRead3MFEdgeCases:
    def test_missing_model_file(self, tmp_path: Path) -> None:
        """3MF with no 3dmodel.model should raise ThreeMFError."""
        p = tmp_path / "empty.3mf"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("readme.txt", "no model here")
        with pytest.raises(ThreeMFError, match="No 3dmodel.model"):
            read_3mf(p)

    def test_invalid_model_xml(self, tmp_path: Path) -> None:
        """Corrupt XML inside model file."""
        p = tmp_path / "bad_xml.3mf"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("3D/3dmodel.model", b"<not valid xml>>>")
        with pytest.raises(ThreeMFError, match="Invalid XML"):
            read_3mf(p)

    def test_no_objects(self, tmp_path: Path) -> None:
        """Model with no <object> elements."""
        model_xml = f'<model xmlns="{NS_CORE}" unit="millimeter"><resources/><build/></model>'
        p = tmp_path / "no_obj.3mf"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("3D/3dmodel.model", model_xml.encode())
        with pytest.raises(ThreeMFError, match="No .object. elements"):
            read_3mf(p)

    def test_missing_mesh(self, tmp_path: Path) -> None:
        """Object with no <mesh> element."""
        model_xml = (
            f'<model xmlns="{NS_CORE}" unit="millimeter">'
            f'<resources><object id="1" type="model"/></resources>'
            f'<build/></model>'
        )
        p = tmp_path / "no_mesh.3mf"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("3D/3dmodel.model", model_xml.encode())
        with pytest.raises(ThreeMFError, match="No .mesh. element"):
            read_3mf(p)

    def test_missing_vertices(self, tmp_path: Path) -> None:
        """Mesh with no <vertices>."""
        model_xml = (
            f'<model xmlns="{NS_CORE}" unit="millimeter">'
            f'<resources><object id="1" type="model"><mesh>'
            f'<triangles/>'
            f'</mesh></object></resources>'
            f'<build/></model>'
        )
        p = tmp_path / "no_verts.3mf"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("3D/3dmodel.model", model_xml.encode())
        with pytest.raises(ThreeMFError, match="No .vertices. element"):
            read_3mf(p)

    def test_missing_triangles(self, tmp_path: Path) -> None:
        """Mesh with no <triangles>."""
        model_xml = (
            f'<model xmlns="{NS_CORE}" unit="millimeter">'
            f'<resources><object id="1" type="model"><mesh>'
            f'<vertices><vertex x="0" y="0" z="0"/></vertices>'
            f'</mesh></object></resources>'
            f'<build/></model>'
        )
        p = tmp_path / "no_tris.3mf"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("3D/3dmodel.model", model_xml.encode())
        with pytest.raises(ThreeMFError, match="No .triangles. element"):
            read_3mf(p)

    def test_no_slic3r_config(self, tmp_path: Path) -> None:
        """3MF without Slic3r_PE_model.config defaults to filament 1."""
        nsmap = {None: NS_CORE}
        root = etree.Element("model", nsmap=nsmap)
        root.set("unit", "millimeter")
        resources = etree.SubElement(root, "resources")
        obj = etree.SubElement(resources, "object", id="1", type="model")
        mesh_el = etree.SubElement(obj, "mesh")
        verts_el = etree.SubElement(mesh_el, "vertices")
        for x, y, z in [(0, 0, 0), (1, 0, 0), (0, 1, 0)]:
            etree.SubElement(verts_el, "vertex", x=str(x), y=str(y), z=str(z))
        tris_el = etree.SubElement(mesh_el, "triangles")
        etree.SubElement(tris_el, "triangle", v1="0", v2="1", v3="2")
        build = etree.SubElement(root, "build")
        etree.SubElement(build, "item", objectid="1")
        model_bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8")

        p = tmp_path / "no_config.3mf"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types/>")
            zf.writestr("3D/3dmodel.model", model_bytes)
        data = read_3mf(p)
        assert data.default_filament == 1

    def test_object_without_type(self, tmp_path: Path) -> None:
        """Object element without type='model' attribute — fallback search."""
        nsmap = {None: NS_CORE}
        root = etree.Element("model", nsmap=nsmap)
        root.set("unit", "millimeter")
        resources = etree.SubElement(root, "resources")
        obj = etree.SubElement(resources, "object", id="1")  # no type attr
        mesh_el = etree.SubElement(obj, "mesh")
        verts_el = etree.SubElement(mesh_el, "vertices")
        for x, y, z in [(0, 0, 0), (1, 0, 0), (0, 1, 0)]:
            etree.SubElement(verts_el, "vertex", x=str(x), y=str(y), z=str(z))
        tris_el = etree.SubElement(mesh_el, "triangles")
        etree.SubElement(tris_el, "triangle", v1="0", v2="1", v3="2")
        build = etree.SubElement(root, "build")
        etree.SubElement(build, "item", objectid="1")
        model_bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8")

        p = tmp_path / "no_type.3mf"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types/>")
            zf.writestr("3D/3dmodel.model", model_bytes)
        data = read_3mf(p)
        assert data.faces.shape == (1, 3)
