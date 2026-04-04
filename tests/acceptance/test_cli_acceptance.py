"""Acceptance tests for the CLI interface."""

import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
import trimesh
from click.testing import CliRunner
from lxml import etree

from full_spectrum.cli import main
from full_spectrum.threemf import NS_CORE, NS_SLIC3RPE


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def cube_stl(tmp_path: Path) -> Path:
    mesh = trimesh.creation.box(extents=[10, 10, 10])
    out = tmp_path / "cube.stl"
    mesh.export(str(out))
    return out


@pytest.fixture
def valid_config(tmp_path: Path) -> Path:
    config = {
        "layer_height_mm": 0.1,
        "target_format": "both",
        "color_mappings": [
            {
                "input_filament": 1,
                "output_palette": {"type": "cyclic", "pattern": [1, 2]},
            }
        ],
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(config), encoding="utf-8")
    return p


class TestCLIBasic:
    def test_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Full Spectrum" in result.output

    def test_version(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output


class TestCLISuccess:
    def test_stl_with_layer_height(
        self, runner: CliRunner, cube_stl: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "out.3mf"
        result = runner.invoke(main, [str(cube_stl), "-l", "0.1", "-o", str(out)])
        assert result.exit_code == 0
        assert out.exists()

    def test_stl_with_config(
        self,
        runner: CliRunner,
        cube_stl: Path,
        valid_config: Path,
        tmp_path: Path,
    ) -> None:
        out = tmp_path / "out.3mf"
        result = runner.invoke(
            main, [str(cube_stl), "-c", str(valid_config), "-o", str(out)]
        )
        assert result.exit_code == 0
        assert out.exists()

    def test_output_default_name(self, runner: CliRunner, cube_stl: Path) -> None:
        result = runner.invoke(main, [str(cube_stl), "-l", "0.1"])
        assert result.exit_code == 0
        assert "cube_painted.3mf" in result.output

    def test_format_prusaslicer(
        self, runner: CliRunner, cube_stl: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "out.3mf"
        result = runner.invoke(
            main,
            [str(cube_stl), "-l", "0.1", "--format", "prusaslicer", "-o", str(out)],
        )
        assert result.exit_code == 0

    def test_format_bambu(
        self, runner: CliRunner, cube_stl: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "out.3mf"
        result = runner.invoke(
            main,
            [str(cube_stl), "-l", "0.1", "--format", "bambu", "-o", str(out)],
        )
        assert result.exit_code == 0

    def test_dry_run(
        self, runner: CliRunner, cube_stl: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "should_not_exist.3mf"
        result = runner.invoke(
            main, [str(cube_stl), "-l", "0.1", "--dry-run", "-o", str(out)]
        )
        assert result.exit_code == 0
        assert "Dry run" in result.output
        assert not out.exists()

    def test_verbose(
        self, runner: CliRunner, cube_stl: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "out.3mf"
        result = runner.invoke(
            main, [str(cube_stl), "-l", "0.1", "-v", "-o", str(out)]
        )
        assert result.exit_code == 0
        assert "Faces:" in result.output

    def test_quiet(
        self, runner: CliRunner, cube_stl: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "out.3mf"
        result = runner.invoke(
            main, [str(cube_stl), "-l", "0.1", "-q", "-o", str(out)]
        )
        assert result.exit_code == 0
        assert result.output.strip() == ""


class TestCLIErrors:
    def test_missing_layer_height(self, runner: CliRunner, cube_stl: Path) -> None:
        result = runner.invoke(main, [str(cube_stl)])
        assert result.exit_code == 2

    def test_invalid_input(self, runner: CliRunner, tmp_path: Path) -> None:
        bad = tmp_path / "bad.stl"
        bad.write_bytes(b"not a mesh")
        result = runner.invoke(main, [str(bad), "-l", "0.1"])
        assert result.exit_code == 1

    def test_invalid_config(
        self, runner: CliRunner, cube_stl: Path, tmp_path: Path
    ) -> None:
        bad_cfg = tmp_path / "bad.json"
        bad_cfg.write_text("{not valid}", encoding="utf-8")
        result = runner.invoke(main, [str(cube_stl), "-c", str(bad_cfg)])
        assert result.exit_code == 2


class TestCLIConfigOverrides:
    def test_config_with_layer_height_override(
        self, runner: CliRunner, cube_stl: Path, valid_config: Path, tmp_path: Path
    ) -> None:
        """--layer-height overrides config's layer_height_mm (cli.py line ~100)."""
        out = tmp_path / "out.3mf"
        result = runner.invoke(
            main,
            [str(cube_stl), "-c", str(valid_config), "-l", "0.12", "-o", str(out)],
        )
        assert result.exit_code == 0
        assert out.exists()

    def test_config_with_format_override(
        self, runner: CliRunner, cube_stl: Path, valid_config: Path, tmp_path: Path
    ) -> None:
        """--format overrides config's target_format (cli.py line ~125)."""
        out = tmp_path / "out.3mf"
        result = runner.invoke(
            main,
            [str(cube_stl), "-c", str(valid_config), "--format", "bambu", "-o", str(out)],
        )
        assert result.exit_code == 0


class TestCLIFlatten:
    def test_flatten_flag(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """--flatten passes through to pipeline for sub-painted 3MF."""
        # Build a 3MF with sub-painted triangles
        verts = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)]
        tris = [(0, 1, 2), (0, 2, 3)]
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
        # Face 0: sub-painted (two hex codes = sub-painted)
        attrib0 = {"v1": "0", "v2": "1", "v3": "2"}
        attrib0[f"{{{NS_SLIC3RPE}}}mmu_segmentation"] = "0C1C"
        etree.SubElement(tris_el, "triangle", **attrib0)
        # Face 1: normal
        etree.SubElement(tris_el, "triangle", v1="0", v2="2", v3="3")
        build = etree.SubElement(root, "build")
        etree.SubElement(build, "item", objectid="1")

        model_bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
        config_xml = b'<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <object id="1">\n    <metadata type="object" key="extruder" value="1"/>\n  </object>\n</config>'

        sub_3mf = tmp_path / "sub.3mf"
        with zipfile.ZipFile(sub_3mf, "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types/>")
            zf.writestr("_rels/.rels", "<Relationships/>")
            zf.writestr("3D/3dmodel.model", model_bytes)
            zf.writestr("Metadata/Slic3r_PE_model.config", config_xml)

        out = tmp_path / "flat.3mf"
        # Without --flatten should fail (exit 1)
        result = runner.invoke(main, [str(sub_3mf), "-l", "0.1", "-o", str(out)])
        assert result.exit_code == 1

        # With --flatten should succeed
        result = runner.invoke(
            main, [str(sub_3mf), "-l", "0.1", "--flatten", "-o", str(out)]
        )
        assert result.exit_code == 0


class TestCLIExceptionHandling:
    def test_oserror(self, runner: CliRunner, cube_stl: Path) -> None:
        """OSError handler (cli.py line ~163)."""
        with patch("full_spectrum.cli.process", side_effect=OSError("disk full")):
            result = runner.invoke(main, [str(cube_stl), "-l", "0.1"])
        assert result.exit_code == 3
        assert "I/O error" in result.output

    def test_unexpected_error(self, runner: CliRunner, cube_stl: Path) -> None:
        """General Exception handler (cli.py line ~166)."""
        with patch("full_spectrum.cli.process", side_effect=RuntimeError("boom")):
            result = runner.invoke(main, [str(cube_stl), "-l", "0.1"])
        assert result.exit_code == 4
        assert "Unexpected error" in result.output


class TestBoundarySplitCLI:
    def test_boundary_split_flag(self, runner: CliRunner, cube_stl: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.3mf"
        result = runner.invoke(main, [
            str(cube_stl), "-l", "0.1", "-o", str(out), "--boundary-split"
        ])
        assert result.exit_code == 0
        assert out.exists()

    def test_no_boundary_split_flag(self, runner: CliRunner, cube_stl: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.3mf"
        result = runner.invoke(main, [
            str(cube_stl), "-l", "0.1", "-o", str(out), "--no-boundary-split"
        ])
        assert result.exit_code == 0

    def test_max_split_depth_flag(self, runner: CliRunner, cube_stl: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.3mf"
        result = runner.invoke(main, [
            str(cube_stl), "-l", "0.1", "-o", str(out),
            "--boundary-split", "--max-split-depth", "4"
        ])
        assert result.exit_code == 0

    def test_verbose_boundary_stats(self, runner: CliRunner, cube_stl: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.3mf"
        result = runner.invoke(main, [
            str(cube_stl), "-l", "0.1", "-o", str(out),
            "--boundary-split", "-v"
        ])
        assert result.exit_code == 0
        assert "Boundary faces:" in result.output

    def test_geometry_slice_flag(self, runner: CliRunner, cube_stl: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.3mf"
        result = runner.invoke(main, [
            str(cube_stl), "-l", "0.1", "-o", str(out), "--geometry-slice"
        ])
        assert result.exit_code == 0
        assert out.exists()
