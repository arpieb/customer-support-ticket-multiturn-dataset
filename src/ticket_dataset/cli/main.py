"""The command-line interface (contracts/cli.md).

A thin wrapper: it parses arguments, calls the programmatic API, renders a report, and exits
with a status derived from the run's outcome. It carries no generation, validation, or scanning
logic of its own, so the machine verdict and the human text cannot disagree (FR-036).

stdout carries machine-readable output only; progress and human text go to stderr, so a piped
invocation is never corrupted by progress lines.
"""

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from ticket_dataset.config.loader import load_config
from ticket_dataset.errors import TicketDatasetError
from ticket_dataset.run.enums import RunOutcome

app = typer.Typer(
    add_completion=False,
    help="Generate reproducible multi-turn customer support ticket datasets.",
)

#: Exit statuses (contracts/cli.md). The four map onto the four run outcomes, because a binary
#: cannot carry the distinction between nothing spent, output that did not qualify, and work
#: that is preserved and resumable (FR-036b).
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2
EXIT_STOPPED = 3

_OUTCOME_STATUS = {
    RunOutcome.COMPLETED: EXIT_OK,
    RunOutcome.FAILED: EXIT_FAILED,
    RunOutcome.REFUSED: EXIT_REFUSED,
    RunOutcome.STOPPED: EXIT_STOPPED,
}


def _note(message: str) -> None:
    print(message, file=sys.stderr)


@app.command()
def generate(
    config: Annotated[Path, typer.Option(help="The single serialized configuration.")],
    seed: Annotated[int, typer.Option(help="Explicit run seed; there is no default.")],
    out: Annotated[Path | None, typer.Option(help="Override the configured output path.")] = None,
    resume: Annotated[
        bool, typer.Option("--resume", help="Continue a checkpointed run for these inputs.")
    ] = False,
    run_id: Annotated[
        str | None, typer.Option(help="Name the run to resume when several match.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Validate and plan without calling a model.")
    ] = False,
    quiet: Annotated[bool, typer.Option("--quiet", help="Suppress progress on stderr.")] = False,
) -> None:
    """Produce a corpus."""
    # Imported here so `--help` and a refused config never pay for the model stack.
    from ticket_dataset.model.anthropic_client import AnthropicModelClient
    from ticket_dataset.run.run import GenerationRun

    try:
        loaded = load_config(config)
        if out is not None:
            loaded = loaded.model_copy(update={"output_path": out})
    except TicketDatasetError as error:
        # Nothing was generated and nothing was spent, which is what exit 2 means.
        _note(str(error))
        raise typer.Exit(EXIT_REFUSED) from error

    try:
        run = GenerationRun(
            config=loaded,
            seed=seed,
            model_client=AnthropicModelClient(loaded),
            run_id=run_id or "",
        )
        slots = run.prepare()
    except TicketDatasetError as error:
        _note(str(error))
        raise typer.Exit(EXIT_REFUSED) from error

    if dry_run:
        plan = {
            "run_id": run.run_id,
            "slots": len(slots),
            "subdomains": len(run.document.subdomains) if run.document else 0,
            "rubric_id": run.rubric.rubric_id if run.rubric else "",
            "output_path": str(loaded.output_path),
            "model_calls_estimated": len(slots) * 2,
        }
        print(json.dumps(plan, indent=2))
        raise typer.Exit(EXIT_OK)

    if not quiet:
        _note(f"run {run.run_id}: generating {len(slots)} records into {run.staging_path}")

    import asyncio

    result = asyncio.run(run.execute())
    summary = {
        "run_id": result.run_id,
        "outcome": result.outcome.value,
        "records_written": result.records_written,
        "records_generated": result.stats.records_generated,
        "discards": {reason.value: count for reason, count in result.stats.discards.items()},
        "duplicates": result.duplicates,
        "staging_path": str(result.staging_path),
    }
    print(json.dumps(summary, indent=2))
    if not quiet:
        _note(
            f"run {result.run_id}: {result.outcome.value}, "
            f"{result.records_written} records in staging"
        )
        # Until the privacy gate lands, nothing may move to the release path (Constitution IV).
        _note("note: output is in staging and has passed no privacy scan; it is not release output")
    raise typer.Exit(_OUTCOME_STATUS[result.outcome])


privacy_app = typer.Typer(help="Inspect and manage the privacy gate.")
app.add_typer(privacy_app, name="privacy")


@privacy_app.command("scan")
def privacy_scan(
    path: Annotated[Path, typer.Argument(help="A JSONL corpus or staging file to examine.")],
    exceptions: Annotated[Path, typer.Option(help="Approved-exception fingerprints.")] = Path(
        "privacy/exceptions.json"
    ),
    report: Annotated[Path | None, typer.Option(help="Write the report to a file.")] = None,
) -> None:
    """Scan an existing artifact, independently of a generation run.

    The path is deliberately unrestricted, which is shared surface with feature 002 (spec
    Assumptions): re-running generation to verify one approval would cost two model calls per
    record. 002 is expected to reuse this rather than grow a second scanner.
    """
    import json as _json

    from ticket_dataset.privacy.canaries import FLOOR_CANARIES
    from ticket_dataset.privacy.detectors.datafog_detector import DataFogDetector
    from ticket_dataset.privacy.exceptions_store import ExceptionStore, fingerprint
    from ticket_dataset.privacy.registry import DetectorRegistry

    if not path.exists():
        _note(f"{path} does not exist")
        raise typer.Exit(EXIT_REFUSED)

    registry = DetectorRegistry()
    registry.register(DataFogDetector())
    registry.approvals = ExceptionStore.load(exceptions).fingerprints
    registry.fingerprinter = fingerprint
    try:
        registry.assert_floor_covered(FLOOR_CANARIES)
    except TicketDatasetError as error:
        _note(str(error))
        raise typer.Exit(EXIT_REFUSED) from error

    records = [_json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    result = registry.scan_records(records)
    rendered = {
        "path": str(path),
        # Counts distinguish a clean result from a scan that examined nothing (FR-023).
        "records_examined": result.records_examined,
        "fields_examined": result.fields_examined,
        "scanned_fields": list(result.scanned_fields),
        "detectors_run": list(result.detectors_run),
        "covered_types": list(result.covered_types),
        "declared_gaps": list(result.declared_gaps),
        "findings": [
            {
                "record_id": finding.record_id,
                "field": finding.field,
                "category": finding.category.value,
                "detector": finding.detector,
                "status": finding.status.value,
                "masked": finding.masked,
            }
            for finding in result.findings
        ],
        "blocking": len(result.blocking),
    }
    output = _json.dumps(rendered, indent=2)
    if report is not None:
        report.write_text(output + "\n")
        _note(f"wrote {report}")
    else:
        print(output)
    raise typer.Exit(EXIT_OK if not result.blocking else EXIT_FAILED)


@privacy_app.command("approve")
def privacy_approve(
    category: Annotated[str, typer.Option(help="The PII category of the finding.")],
    reason: Annotated[str, typer.Option(help="Why this value is legitimately synthetic.")],
    by: Annotated[str, typer.Option("--by", help="Who is approving. Recorded, not checked.")],
    value: Annotated[
        str | None, typer.Option(help="The value; fingerprinted, never stored.")
    ] = None,
    from_quarantine: Annotated[
        Path | None, typer.Option("--from-quarantine", help="Read the value from quarantine.")
    ] = None,
    record_id: Annotated[str | None, typer.Option(help="With --from-quarantine.")] = None,
    field_name: Annotated[
        str | None, typer.Option("--field", help="With --from-quarantine, e.g. turns[3].content.")
    ] = None,
    exceptions: Annotated[Path, typer.Option(help="Where approvals are recorded.")] = Path(
        "privacy/exceptions.json"
    ),
) -> None:
    """Record a reviewed finding as an approved exception (FR-022, FR-022a, FR-022b)."""
    from ticket_dataset.privacy.detectors.datafog_detector import DataFogDetector
    from ticket_dataset.privacy.exceptions_store import ExceptionStore
    from ticket_dataset.privacy.quarantine import Quarantine
    from ticket_dataset.run.enums import PIICategory

    try:
        pii_category = PIICategory(category.upper())
    except ValueError as error:
        _note(f"unknown category {category!r}; expected one of {[c.value for c in PIICategory]}")
        raise typer.Exit(EXIT_REFUSED) from error

    if from_quarantine is not None:
        if not (record_id and field_name):
            _note("--from-quarantine needs --record-id and --field")
            raise typer.Exit(EXIT_REFUSED)
        # Read in place, so the reviewer never has to retype or paste the value.
        value = Quarantine(path=from_quarantine).find(record_id, field_name)
        if value is None:
            _note(f"no such finding in {from_quarantine}: {record_id} / {field_name}")
            raise typer.Exit(EXIT_REFUSED)
    if not value:
        _note("supply --value, or --from-quarantine with --record-id and --field")
        raise typer.Exit(EXIT_REFUSED)

    detector = DataFogDetector()
    store = ExceptionStore.load(exceptions)
    try:
        entry = store.approve(
            category=pii_category,
            value=value,
            reason=reason,
            approved_by=by,
            scan_reason=lambda text: detector.scan(text),
        )
    except (TicketDatasetError, ValueError) as error:
        _note(str(error))
        raise typer.Exit(EXIT_REFUSED) from error
    store.save()
    _note(f"approved {entry.fingerprint[:12]}… ({entry.category}) by {entry.approved_by}")
    raise typer.Exit(EXIT_OK)


@app.command("schema")
def schema_export(
    out: Annotated[Path | None, typer.Option(help="Write to a file instead of stdout.")] = None,
) -> None:
    """Write the JSON Schema export of the record contract (Constitution I)."""
    from ticket_dataset.schema.export import export_json_schema

    rendered = json.dumps(export_json_schema(), indent=2) + "\n"
    if out is None:
        print(rendered, end="")
    else:
        Path(out).write_text(rendered)
        _note(f"wrote {out}")


if __name__ == "__main__":  # pragma: no cover
    app()
