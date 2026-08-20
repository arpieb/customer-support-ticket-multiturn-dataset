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
        run = GenerationRun(config=loaded, seed=seed, model_client=AnthropicModelClient(loaded))
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
