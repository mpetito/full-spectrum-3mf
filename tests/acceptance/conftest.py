import json
import os
import subprocess
import zipfile
from pathlib import Path
from typing import NamedTuple

import pytest
from click.testing import CliRunner

from full_spectrum.cli import main


class SlicerInfo(NamedTuple):
    path: Path
    slicer_type: str  # "bambu" or "orca"


@pytest.fixture(scope="session")
def slicer_info():
    """Discover slicer binary from environment variables.

    BambuStudio is preferred because self-contained BBL 3MF files (with
    embedded project settings) can be sliced without supplying external
    profiles.  OrcaSlicer is supported as a fallback.
    """
    # BambuStudio checked first: OrcaSlicer 2.3.x rejects BambuStudio 2.5
    # fixture files (version-check failure).  Revisit when OrcaSlicer adds
    # compatibility or we provide OrcaSlicer-native fixtures.
    for env_var, slicer_type in [
        ("BAMBUSTUDIO_BIN", "bambu"),
        ("ORCASLICER_BIN", "orca"),
    ]:
        path_str = os.environ.get(env_var)
        if path_str:
            p = Path(path_str)
            if p.is_file():
                return SlicerInfo(path=p, slicer_type=slicer_type)
    pytest.skip("No slicer binary available (set BAMBUSTUDIO_BIN or ORCASLICER_BIN)")


@pytest.fixture(scope="session")
def slice_3mf(slicer_info, tmp_path_factory):
    """Factory fixture: slices a self-contained BBL 3MF and returns G-code.

    The input 3MF must embed its own project settings (machine, process,
    filament) so no external profiles are needed.
    """

    def _slice(input_3mf: Path) -> str:
        work_dir = tmp_path_factory.mktemp("slicer")
        output_3mf = work_dir / "sliced_output.3mf"

        # OrcaSlicer uses underscore, BambuStudio uses hyphen.
        export_flag = (
            "--export_3mf" if slicer_info.slicer_type == "orca"
            else "--export-3mf"
        )
        cmd = [
            str(slicer_info.path),
            "--slice", "1",
            export_flag, str(output_3mf),
            str(input_3mf),
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, cwd=work_dir,
        )

        if result.returncode != 0:
            pytest.fail(
                f"Slicer failed (exit {result.returncode}):\n"
                f"stdout: {result.stdout[-2000:]}\n"
                f"stderr: {result.stderr[-2000:]}"
            )

        with zipfile.ZipFile(output_3mf, "r") as zf:
            gcode_candidates = sorted(
                n for n in zf.namelist()
                if n.startswith("Metadata/") and n.endswith(".gcode")
            )
            if not gcode_candidates:
                pytest.fail(f"No G-code in output 3MF. Contents: {zf.namelist()}")
            # Prefer plate_1; sorted() ensures deterministic order.
            return zf.read(gcode_candidates[0]).decode("utf-8")

    return _slice


@pytest.fixture(scope="session")
def run_full_spectrum():
    """Factory fixture: runs the full-spectrum CLI via CliRunner."""

    def _run(input_path: Path, config: dict, output_path: Path) -> None:
        config_path = output_path.parent / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(main, [
            str(input_path),
            "-c", str(config_path),
            "-o", str(output_path),
        ])
        assert result.exit_code == 0, (
            f"full-spectrum CLI failed (exit {result.exit_code}):\n{result.output}"
        )

    return _run
