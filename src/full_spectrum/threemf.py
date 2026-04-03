"""3MF ZIP archive reading and writing."""

from __future__ import annotations

import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from lxml import etree

logger = logging.getLogger(__name__)

_SECURE_PARSER = etree.XMLParser(resolve_entities=False, no_network=True)

from full_spectrum.encoding import filament_to_hex, hex_to_filament, is_sub_painted


class ThreeMFError(Exception):
    """Raised for 3MF parsing or writing errors."""


NS_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
NS_SLIC3RPE = "http://schemas.slic3r.org/3mf/2017/06"
NS_P = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"

NAMESPACES = {"m": NS_CORE, "slic3rpe": NS_SLIC3RPE, "p": NS_P}

CONTENT_TYPES_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>"""

RELS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0"
    Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>"""

CONFIG_XML_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="1">
    <metadata type="object" key="extruder" value="{default_filament}"/>
  </object>
</config>"""


@dataclass
class ThreeMFData:
    """Parsed contents of a 3MF file."""
    vertices: np.ndarray          # shape (V, 3) float64
    faces: np.ndarray             # shape (F, 3) int32 — vertex indices
    face_colors: dict[int, int]   # face_index → 1-based filament (only non-default faces)
    default_filament: int = 1


def read_3mf(path: str | Path, flatten: bool = False) -> ThreeMFData:
    """Read a 3MF file and extract geometry + per-triangle filament assignments.

    Args:
        path: Path to .3mf file
        flatten: If True, flatten sub-painted triangles to dominant filament.
                 If False, raise ThreeMFError on sub-painted triangles.
    """
    path = Path(path)
    try:
        zf = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError) as e:
        raise ThreeMFError(f"Cannot open 3MF file {path}: {e}") from e

    with zf:
        # Find model file
        model_path = None
        for name in zf.namelist():
            if name.lower().endswith("3dmodel.model"):
                model_path = name
                break
        if model_path is None:
            raise ThreeMFError(f"No 3dmodel.model found in {path}")

        model_xml = zf.read(model_path)
        try:
            root = etree.fromstring(model_xml, parser=_SECURE_PARSER)
        except etree.XMLSyntaxError as e:
            raise ThreeMFError(f"Invalid XML in {model_path}: {e}") from e

        # Find object with mesh — resolve component references if needed
        mesh_el = _find_mesh_element(root, zf)

        # Parse vertices
        vertices_el = mesh_el.find("m:vertices", NAMESPACES)
        if vertices_el is None:
            raise ThreeMFError("No <vertices> element found")

        verts = []
        for v in vertices_el.findall("m:vertex", NAMESPACES):
            verts.append([float(v.get("x", 0)), float(v.get("y", 0)), float(v.get("z", 0))])
        vertices = np.array(verts, dtype=np.float64)

        # Parse triangles
        triangles_el = mesh_el.find("m:triangles", NAMESPACES)
        if triangles_el is None:
            raise ThreeMFError("No <triangles> element found")

        faces_list = []
        face_colors: dict[int, int] = {}
        n_verts = len(verts)

        for i, tri in enumerate(triangles_el.findall("m:triangle", NAMESPACES)):
            v1 = int(tri.get("v1", 0))
            v2 = int(tri.get("v2", 0))
            v3 = int(tri.get("v3", 0))
            if not (0 <= v1 < n_verts and 0 <= v2 < n_verts and 0 <= v3 < n_verts):
                raise ThreeMFError(
                    f"Face {i}: vertex index out of bounds "
                    f"(v1={v1}, v2={v2}, v3={v3}, max={n_verts - 1})"
                )
            faces_list.append([v1, v2, v3])

            # Check for color attributes
            hex_str = tri.get(f"{{{NS_SLIC3RPE}}}mmu_segmentation")
            if hex_str is None:
                hex_str = tri.get("paint_color")

            if hex_str is not None and hex_str.strip():
                hex_str = hex_str.strip()
                if is_sub_painted(hex_str):
                    if not flatten:
                        raise ThreeMFError(
                            f"Sub-painted triangle detected at face {i}: {hex_str!r}. "
                            "Use --flatten to simplify to dominant filament."
                        )
                    # Flatten: take first 2 chars as dominant
                    hex_str = hex_str[:2] if len(hex_str) >= 2 else hex_str[:1]
                try:
                    face_colors[i] = hex_to_filament(hex_str)
                except ValueError as e:
                    raise ThreeMFError(f"Face {i}: {e}") from e

        faces = np.array(faces_list, dtype=np.int32)

        # Parse default filament
        default_filament = _parse_default_filament(zf)

    return ThreeMFData(
        vertices=vertices,
        faces=faces,
        face_colors=face_colors,
        default_filament=default_filament,
    )


def _find_mesh_element(
    root: etree._Element, zf: zipfile.ZipFile
) -> etree._Element:
    """Find the <mesh> element, resolving component references if needed.

    BambuStudio uses a component-based layout where the main 3dmodel.model
    contains <object><components><component p:path="..."/></object> and the
    actual mesh lives in a separate .model file inside the ZIP.
    """
    objects = root.findall(".//m:object[@type='model']", NAMESPACES)
    if len(objects) == 0:
        objects = root.findall(".//m:object", NAMESPACES)
    if len(objects) == 0:
        raise ThreeMFError("No <object> elements found in 3MF model")

    # Try each object for a direct mesh first
    for obj in objects:
        mesh_el = obj.find("m:mesh", NAMESPACES)
        if mesh_el is not None:
            return mesh_el

    # No direct mesh found — look for component references
    for obj in objects:
        components = obj.find("m:components", NAMESPACES)
        if components is None:
            continue
        for comp in components.findall("m:component", NAMESPACES):
            comp_path = comp.get(f"{{{NS_P}}}path")
            if comp_path is None:
                continue
            # Resolve path: strip leading slash, normalize
            comp_path = comp_path.lstrip("/")
            if comp_path not in zf.namelist():
                continue
            try:
                comp_xml = zf.read(comp_path)
                comp_root = etree.fromstring(comp_xml, parser=_SECURE_PARSER)
            except (etree.XMLSyntaxError, KeyError):
                continue
            # Find mesh in component model
            for comp_obj in comp_root.findall(".//m:object", NAMESPACES):
                mesh_el = comp_obj.find("m:mesh", NAMESPACES)
                if mesh_el is not None:
                    logger.warning(
                        "Using first component mesh found; "
                        "multi-component files may lose geometry"
                    )
                    return mesh_el

    raise ThreeMFError("No <mesh> element found in object or its components")


def _parse_default_filament(zf: zipfile.ZipFile) -> int:
    """Parse default filament from slicer config metadata if present.

    Checks Slic3r_PE_model.config (PrusaSlicer) and model_settings.config
    (BambuStudio/OrcaSlicer).
    """
    for name in zf.namelist():
        lower = name.lower()
        if "slic3r_pe_model.config" in lower or "model_settings.config" in lower:
            try:
                config_xml = zf.read(name)
                root = etree.fromstring(config_xml, parser=_SECURE_PARSER)
                for meta in root.iter():
                    if meta.tag == "metadata" and meta.get("key") == "extruder":
                        return int(meta.get("value", "1"))
            except (etree.XMLSyntaxError, ValueError) as e:
                logger.warning("Failed to parse slicer config in %s: %s", name, e)
                continue
    return 1


def write_3mf(
    output_path: str | Path,
    vertices: np.ndarray,
    faces: np.ndarray,
    face_filaments: np.ndarray,
    default_filament: int = 1,
    target_format: str = "both",
) -> None:
    """Write a 3MF file with per-triangle filament slot assignments.

    Args:
        output_path: Output .3mf file path
        vertices: (V, 3) float array of vertex coordinates
        faces: (F, 3) int array of vertex indices per triangle
        face_filaments: (F,) int array of 1-based filament per face
        default_filament: Default filament for the object
        target_format: "prusaslicer", "bambu", or "both"
    """
    output_path = Path(output_path)

    # Build 3dmodel.model XML
    nsmap = {None: NS_CORE}
    write_slic3rpe = target_format in ("prusaslicer", "both")
    write_paint = target_format in ("bambu", "both")

    if write_slic3rpe:
        nsmap["slic3rpe"] = NS_SLIC3RPE

    root = etree.Element("model", nsmap=nsmap)
    root.set("unit", "millimeter")
    root.set("{http://www.w3.org/XML/1998/namespace}lang", "en-US")

    resources = etree.SubElement(root, "resources")
    obj = etree.SubElement(resources, "object", id="1", type="model")
    mesh_el = etree.SubElement(obj, "mesh")

    # Vertices
    verts_el = etree.SubElement(mesh_el, "vertices")
    for v in vertices:
        etree.SubElement(verts_el, "vertex", x=str(v[0]), y=str(v[1]), z=str(v[2]))

    # Triangles
    tris_el = etree.SubElement(mesh_el, "triangles")
    for i, face in enumerate(faces):
        attrib = {"v1": str(face[0]), "v2": str(face[1]), "v3": str(face[2])}
        filament = int(face_filaments[i])

        if filament != default_filament:
            hex_code = filament_to_hex(filament)
            if write_slic3rpe:
                attrib[f"{{{NS_SLIC3RPE}}}mmu_segmentation"] = hex_code
            if write_paint:
                attrib["paint_color"] = hex_code

        etree.SubElement(tris_el, "triangle", **attrib)

    # Build element
    build = etree.SubElement(root, "build")
    etree.SubElement(
        build, "item",
        objectid="1",
        transform="1 0 0 0 1 0 0 0 1 0 0 0",
        printable="1",
    )

    # Serialize XML
    model_bytes = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", pretty_print=True
    )

    # Validate the output XML
    try:
        etree.fromstring(model_bytes)
    except etree.XMLSyntaxError as e:
        raise ThreeMFError(f"Generated invalid XML: {e}") from e

    # Build config XML
    config_xml = CONFIG_XML_TEMPLATE.format(default_filament=default_filament).encode("utf-8")

    # Pack into ZIP
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        zf.writestr("_rels/.rels", RELS_XML)
        zf.writestr("3D/3dmodel.model", model_bytes)
        zf.writestr("Metadata/Slic3r_PE_model.config", config_xml)
