"""Click-based CLI for Full Spectrum 3MF."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from full_spectrum import __version__
from full_spectrum.config import (
    ConfigError,
    FullSpectrumConfig,
    default_config,
    load_config,
    validate_config,
)
from full_spectrum.mesh import MeshError
from full_spectrum.pipeline import process
from full_spectrum.threemf import ThreeMFError

logger = logging.getLogger("full_spectrum")


def _setup_logging(verbose: bool, quiet: bool) -> None:
    level = logging.WARNING
    if verbose:
        level = logging.DEBUG
    elif quiet:
        level = logging.ERROR
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


@click.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option(
    "-l",
    "--layer-height",
    type=float,
    default=None,
    help="Layer height in mm (0.04–0.2). Required if not in config.",
)
@click.option(
    "-c",
    "--config",
    "config_path",
    type=click.Path(exists=True),
    default=None,
    help="Path to JSON palette configuration file.",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(),
    default=None,
    help="Output 3MF file path. Default: <input>_painted.3mf",
)
@click.option(
    "--format",
    "target_format",
    type=click.Choice(["prusaslicer", "bambu", "both"], case_sensitive=False),
    default=None,
    help="Attribute format to write. Default: both.",
)
@click.option(
    "--flatten",
    is_flag=True,
    help="Flatten sub-painted triangles to dominant filament.",
)
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
@click.option("-q", "--quiet", is_flag=True, help="Suppress all non-error output.")
@click.option("--dry-run", is_flag=True, help="Validate without writing output file.")
@click.version_option(version=__version__, prog_name="full-spectrum")
def main(
    input_file: str,
    layer_height: float | None,
    config_path: str | None,
    output_path: str | None,
    target_format: str | None,
    flatten: bool,
    verbose: bool,
    quiet: bool,
    dry_run: bool,
) -> None:
    """Full Spectrum 3MF — Z-layer color dithering for 3D printing.

    Processes INPUT_FILE (STL or 3MF) with per-triangle filament slot
    assignments for optical color blending.
    """
    _setup_logging(verbose, quiet)

    try:
        # Load or build config
        if config_path:
            cfg = load_config(config_path)
            # CLI --layer-height overrides config
            if layer_height is not None:
                cfg = FullSpectrumConfig(
                    layer_height_mm=layer_height,
                    target_format=cfg.target_format,
                    color_mappings=cfg.color_mappings,
                )
        elif layer_height is not None:
            fmt = target_format or "both"
            cfg = default_config(layer_height, fmt)
        else:
            click.echo(
                "Error: Either --config or --layer-height is required.", err=True
            )
            sys.exit(2)

        # CLI --format overrides config
        if target_format is not None:
            cfg = FullSpectrumConfig(
                layer_height_mm=cfg.layer_height_mm,
                target_format=target_format,
                color_mappings=cfg.color_mappings,
            )

        # Validate
        warnings = validate_config(cfg)
        for w in warnings:
            logger.warning(w)

        # Resolve output path
        if output_path is None:
            output_path = str(Path(input_file).stem + "_painted.3mf")

        # Run pipeline
        result = process(
            input_path=input_file,
            config=cfg,
            output_path=output_path,
            flatten=flatten,
            dry_run=dry_run,
        )

        # Report warnings
        for w in result.warnings:
            logger.warning(w)

        # Report results
        if verbose:
            click.echo(f"Faces: {result.face_count}")
            click.echo(f"Layers: {result.layer_count}")
            click.echo(f"Distribution: {result.filament_distribution}")

        if not quiet:
            if dry_run:
                click.echo(f"Dry run complete: {result.face_count} faces validated.")
            else:
                click.echo(f"Wrote {output_path}")

    except ConfigError as e:
        click.echo(f"Config error: {e}", err=True)
        sys.exit(2)
    except (MeshError, ThreeMFError) as e:
        click.echo(f"Input error: {e}", err=True)
        sys.exit(1)
    except OSError as e:
        click.echo(f"I/O error: {e}", err=True)
        sys.exit(3)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        logger.debug("Traceback:", exc_info=True)
        sys.exit(4)
