"""
cli.py — Click entry points: demo, sync, validate, info.

Entry point registered as `rnse` in pyproject.toml.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich import box

err_console = Console(stderr=True)
out_console = Console()


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool, quiet: bool) -> None:
    level = logging.WARNING if quiet else (logging.DEBUG if verbose else logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=err_console, show_path=False, markup=True)],
    )


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
def cli() -> None:
    """Report Number Synchronisation Engine — deterministic Word report automation."""


# ---------------------------------------------------------------------------
# demo command
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--output-dir", default="./demo", show_default=True,
              type=click.Path(), help="Directory to write demo files")
@click.option("--assets", default=3, show_default=True,
              type=click.IntRange(1, 20), help="Number of demo assets to generate")
@click.option("--verbose", is_flag=True, default=False, help="Debug logging")
def demo(output_dir: str, assets: int, verbose: bool) -> None:
    """Generate demo schedule.xlsx and report.docx for immediate testing."""
    _setup_logging(verbose=verbose, quiet=False)
    from rnse.demo import generate_demo_schedule, generate_demo_report, DEMO_ASSETS

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    asset_data = DEMO_ASSETS[:assets]
    schedule_path = generate_demo_schedule(out, asset_data)
    report_path = generate_demo_report(out, asset_data)

    err_console.print(f"[green]Demo files written:[/green]")
    err_console.print(f"  Schedule: {schedule_path}")
    err_console.print(f"  Report:   {report_path}")
    err_console.print(
        f"\nRun: [bold]rnse sync --schedule {schedule_path} --report {report_path}[/bold]"
    )


# ---------------------------------------------------------------------------
# sync command
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--schedule", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to Excel schedule")
@click.option("--report", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to input Word report")
@click.option("--output", default=None, type=click.Path(path_type=Path),
              help="Path for output Word document (default: <report>_synced.docx)")
@click.option("--audit", default="audit.json", show_default=True, type=click.Path(path_type=Path),
              help="Path for audit JSON")
@click.option("--no-audit", is_flag=True, default=False, help="Skip writing audit file")
@click.option("--strict", is_flag=True, default=False,
              help="Abort on any ERROR (not just FATAL)")
@click.option("--quiet", is_flag=True, default=False,
              help="Suppress console output except errors")
@click.option("--verbose", is_flag=True, default=False, help="Debug logging")
def sync(
    schedule: Path,
    report: Path,
    output: Path | None,
    audit: Path,
    no_audit: bool,
    strict: bool,
    quiet: bool,
    verbose: bool,
) -> None:
    """Read schedule, process report, write output document."""
    _setup_logging(verbose=verbose, quiet=quiet)

    from rnse.loader import load_schedule, load_document
    from rnse.validator import validate_schedule, has_fatal, has_errors
    from rnse.engine import substitute_document
    from rnse.reporter import AuditReport

    if output is None:
        output = report.parent / (report.stem + "_synced.docx")

    # --- Load & validate schedule ---
    raw_schedule, field_names = load_schedule(schedule)
    validated_schedule, val_issues = validate_schedule(raw_schedule, field_names, schedule)

    for issue in val_issues:
        err_console.print(f"[{'red' if issue.severity.value != 'WARN' else 'yellow'}]{issue}[/]")

    if has_fatal(val_issues):
        err_console.print("[bold red]FATAL validation errors — aborting.[/bold red]")
        sys.exit(2)

    if strict and has_errors(val_issues):
        err_console.print("[bold red]Errors in schedule (--strict mode) — aborting.[/bold red]")
        sys.exit(2)

    # --- Load document ---
    document = load_document(report)

    # --- Run engine ---
    reporter = AuditReport()
    substitute_document(document, validated_schedule, reporter)

    # --- Save output ---
    document.save(str(output))
    if not quiet:
        err_console.print(f"[green]Output written:[/green] {output}")

    # --- Audit ---
    if not no_audit:
        reporter.write_audit(audit, str(schedule), str(report), str(output))
        # Emit audit path to stdout for piping.
        out_console.print(str(audit))

    if not quiet:
        reporter.print_table()

    if strict and reporter.error_count:
        sys.exit(2)
    elif reporter.error_count:
        sys.exit(1)
    else:
        sys.exit(0)


# ---------------------------------------------------------------------------
# validate command
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--schedule", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to Excel schedule")
@click.option("--report", default=None, type=click.Path(exists=True, path_type=Path),
              help="Path to Word report (optional; validates placeholder syntax)")
@click.option("--quiet", is_flag=True, default=False)
@click.option("--verbose", is_flag=True, default=False)
def validate(schedule: Path, report: Path | None, quiet: bool, verbose: bool) -> None:
    """Validate schedule and/or report without producing output.

    Exit code: 0 = clean, 1 = warnings only, 2 = errors/fatals present.
    """
    _setup_logging(verbose=verbose, quiet=quiet)

    from rnse.loader import load_schedule, load_document
    from rnse.validator import (
        validate_schedule, validate_document_placeholders,
        has_fatal, has_errors, Severity,
    )

    raw_schedule, field_names = load_schedule(schedule)
    validated_schedule, val_issues = validate_schedule(raw_schedule, field_names, schedule)

    all_issues = list(val_issues)

    if not has_fatal(val_issues) and report is not None:
        document = load_document(report)
        doc_issues = validate_document_placeholders(document, validated_schedule)
        all_issues.extend(doc_issues)

    for issue in all_issues:
        colour = "red" if issue.severity in (Severity.FATAL, Severity.ERROR) else "yellow"
        err_console.print(f"[{colour}]{issue}[/]")

    if not all_issues and not quiet:
        err_console.print("[green]Validation passed — no issues found.[/green]")

    if has_fatal(all_issues) or has_errors(all_issues):
        sys.exit(2)
    elif any(i.severity == Severity.WARN for i in all_issues):
        sys.exit(1)
    else:
        sys.exit(0)


# ---------------------------------------------------------------------------
# info command
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--schedule", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to Excel schedule")
@click.option("--verbose", is_flag=True, default=False)
def info(schedule: Path, verbose: bool) -> None:
    """Summarise the schedule: assets, fields, value counts."""
    _setup_logging(verbose=verbose, quiet=False)

    from rnse.loader import load_schedule
    from rnse.validator import validate_schedule

    raw_schedule, field_names = load_schedule(schedule)
    validated_schedule, issues = validate_schedule(raw_schedule, field_names, schedule)

    if not validated_schedule:
        err_console.print("[red]No valid assets found.[/red]")
        for issue in issues:
            err_console.print(f"  {issue}")
        sys.exit(1)

    err_console.print(f"\n[bold]Schedule:[/bold] {schedule}")
    err_console.print(f"[bold]Assets:[/bold]  {len(validated_schedule)}")
    err_console.print(f"[bold]Fields:[/bold]  {', '.join(field_names)}\n")

    t = Table(box=box.ROUNDED, show_header=True, title="Asset Summary")
    t.add_column("Asset_ID", style="bold")
    for fn in field_names:
        t.add_column(fn, justify="right")

    for asset_id, fields in sorted(validated_schedule.items()):
        row = [asset_id]
        for fn in field_names:
            v = fields.get(fn)
            row.append(str(v) if v is not None else "[dim]—[/dim]")
        t.add_row(*row)

    err_console.print(t)

    if issues:
        err_console.print(f"\n[yellow]{len(issues)} validation issue(s):[/yellow]")
        for issue in issues:
            err_console.print(f"  {issue}")
