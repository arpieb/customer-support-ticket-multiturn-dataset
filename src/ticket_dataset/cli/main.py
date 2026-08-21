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
from ticket_dataset.run.progress import ProgressReporter

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
    config: Annotated[
        Path | None, typer.Option(help="The single serialized configuration.")
    ] = None,
    seed: Annotated[
        int | None, typer.Option(help="Explicit run seed; there is no default.")
    ] = None,
    from_manifest: Annotated[
        Path | None,
        typer.Option(
            "--from-manifest",
            help="Reproduce the run a manifest describes, taking its config and its seed.",
        ),
    ] = None,
    allow_drift: Annotated[
        bool,
        typer.Option("--allow-drift", help="Proceed with --from-manifest despite changed inputs."),
    ] = False,
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
    from ticket_dataset.model.litellm_client import LiteLLMModelClient
    from ticket_dataset.run.run import GenerationRun

    try:
        if from_manifest is not None:
            # Silently preferring one source is the error this command exists to prevent, so an
            # ambiguous invocation refuses instead of guessing which one was meant.
            if config is not None:
                raise TicketDatasetError(
                    "--from-manifest carries its own config; pass one or the other"
                )
            if seed is not None:
                raise TicketDatasetError(
                    "--from-manifest reproduces a recorded run, so its seed is the recorded one. "
                    "To reuse the config under a different seed, recover it first: "
                    "ticket-dataset config-from-manifest <manifest> --out <config>"
                )
            loaded, seed = _reproduce_from_manifest(
                from_manifest, allow_drift=allow_drift, output_override=out
            )
        else:
            if config is None or seed is None:
                raise TicketDatasetError(
                    "pass --config with --seed, or --from-manifest to reproduce a recorded run"
                )
            loaded = load_config(config, output_override=out)
    except TicketDatasetError as error:
        # Nothing was generated and nothing was spent, which is what exit 2 means.
        _note(str(error))
        raise typer.Exit(EXIT_REFUSED) from error

    try:
        run = GenerationRun(
            config=loaded,
            seed=seed,
            model_client=LiteLLMModelClient(loaded),
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

    reporter: ProgressReporter | None = None
    last_progress = None
    if not quiet:
        verb = "resuming" if resume else "generating"
        _note(f"run {run.run_id}: {verb} {len(slots)} records into {run.staging_path}")
        # FR-012 asks that progress be observable during a long run. Records reaching the staging
        # file satisfies that literally, but an operator watching a slow model work through a
        # corpus cannot tell a running job from a hung one without this.
        reporter = ProgressReporter(target=loaded.record_count)

        def _observe(progress) -> None:
            nonlocal last_progress
            last_progress = progress
            reporter.update(progress)

        run.on_progress = _observe

    import asyncio

    try:
        result = asyncio.run(run.resume() if resume else run.execute())
    except TicketDatasetError as error:
        if reporter is not None:
            reporter.close()
        _note(str(error))
        raise typer.Exit(EXIT_REFUSED) from error

    if reporter is not None:
        reporter.close(last_progress)

    # One object behind both surfaces, so the machine verdict and the human text cannot disagree
    # (FR-036). stdout carries the report; stderr carries the rendering.
    print(result.report.to_json() if result.report else "{}")
    if not quiet and result.report is not None:
        _note(result.report.render())
    raise typer.Exit(_OUTCOME_STATUS[result.outcome])


@app.command("validate-manifest")
def validate_manifest_command(
    path: Annotated[Path, typer.Argument(help="The manifest to check.")],
) -> None:
    """Check a manifest against its contract and its reconciliation rule (FR-026, FR-028).

    Validation checks the arithmetic, not only that fields are present: a manifest whose fields
    are all there but whose counts do not balance is not valid, and presence checking alone would
    pass exactly the manifests worth catching.
    """
    from ticket_dataset.run.manifest import validate_manifest_file

    problems = validate_manifest_file(path)
    if not problems:
        _note(f"{path}: valid")
        raise typer.Exit(EXIT_OK)
    for problem in problems:
        _note(f"  - {problem}")
    _note(f"{path}: {len(problems)} problem(s)")
    raise typer.Exit(EXIT_FAILED)


def _read_manifest(path: Path) -> dict:
    """Load a manifest, refusing rather than guessing if it is not one."""
    if not path.exists():
        raise TicketDatasetError(f"{path} does not exist")
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise TicketDatasetError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(payload, dict) or "run_id" not in payload:
        raise TicketDatasetError(f"{path} does not look like a run manifest")
    return payload


def _report_reproduction(report) -> None:
    """State the conditions around the config, which the config file cannot carry itself."""
    from ticket_dataset.run.reproduce import InputStatus

    _note(f"run {report.run_id}: seed {report.seed}")
    for check in report.checks:
        if check.status is InputStatus.MATCH:
            _note(f"  {check.label:16} match")
        elif check.status is InputStatus.MISSING:
            _note(f"  {check.label:16} MISSING   {check.path} is not on disk")
        else:
            _note(
                f"  {check.label:16} DIFFERS   recorded {check.recorded[:12]}, "
                f"now {check.actual[:12]} ({check.path})"
            )
    if report.commit:
        dirty = " (uncommitted changes at run time)" if report.dirty else ""
        _note(f"  code_revision    {report.commit[:12]}{dirty}")
    for name, value in report.environment_overrides.items():
        _note(f"  environment      {name}={value} must be set to match")


def _reproduce_from_manifest(
    path: Path, *, allow_drift: bool, output_override: Path | None = None
) -> tuple[object, int]:
    """The config and seed a manifest records, once its other inputs have been checked.

    Drift refuses by default. A rerun against a changed prompt produces a different corpus while
    looking like a faithful reproduction, which is a worse outcome than transcribing the config
    by hand — at least that fails visibly.
    """
    from ticket_dataset.run.reproduce import check_reproduction

    manifest = _read_manifest(path)
    report = check_reproduction(manifest)
    _report_reproduction(report)

    if report.drifted and not allow_drift:
        raise TicketDatasetError(
            "the working tree no longer matches the inputs this run recorded, so it would not "
            "reproduce. Restore them (git checkout "
            f"{(report.commit or '<commit>')[:12]} -- "
            + " ".join(str(c.path) for c in report.drifted)
            + ") or pass --allow-drift to generate a different corpus deliberately."
        )
    if report.drifted:
        _note("  proceeding with --allow-drift: this will NOT reproduce the recorded corpus")

    # A config recovered from a manifest gets no free pass: it goes through the same validation
    # a config read from a file does. Its recorded output_path is normally occupied — the run it
    # describes published there — so --out is how a reproduction is given somewhere to write.
    from ticket_dataset.config.loader import validate_config

    return (
        validate_config(manifest["config"], output_override=output_override),
        report.seed,
    )


@app.command("config-from-manifest")
def config_from_manifest_command(
    path: Annotated[Path, typer.Argument(help="The manifest to recover a config from.")],
    out: Annotated[
        Path | None, typer.Option(help="Write the config here instead of to stdout.")
    ] = None,
) -> None:
    """Recover the configuration a run used, from the manifest it wrote (FR-040).

    The manifest stores the resolved config, so what comes back is what the run actually ran
    with rather than what its author typed. The config alone will not reproduce the run, so the
    conditions around it — seed, input digests, code revision, routing environment — are
    reported alongside it.
    """
    from ticket_dataset.run.reproduce import (
        check_reproduction,
        config_from_manifest,
        render_config_toml,
    )

    try:
        manifest = _read_manifest(path)
        text = render_config_toml(config_from_manifest(manifest))
        report = check_reproduction(manifest)
    except TicketDatasetError as error:
        _note(str(error))
        raise typer.Exit(EXIT_REFUSED) from error

    if out is None:
        print(text, end="")
    else:
        out.write_text(text)
        _note(f"wrote {out}")

    _report_reproduction(report)
    if report.drifted:
        _note("")
        _note("This run cannot be reproduced from the working tree as it stands.")
        raise typer.Exit(EXIT_FAILED)
    if out is not None:
        _note("")
        _note(f"  ticket-dataset generate --config {out} --seed {report.seed}")


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


@app.command("sample-for-review")
def sample_for_review(
    corpus: Annotated[Path, typer.Option(help="The corpus to sample from.")],
    seed: Annotated[int, typer.Option(help="Explicit — the sample is itself reproducible.")],
    n: Annotated[int, typer.Option(help="Sample size.")] = 50,
    out: Annotated[Path | None, typer.Option(help="Write JSONL here instead of stdout.")] = None,
) -> None:
    """Export a seeded random sample with scores, for human calibration (SC-011).

    The calibration judgement is a human act; this exists so it is cheap rather than automated.
    **Nothing enforces that it happens**: no requirement obliges a calibration record to exist or
    a release to cite one (checklist CHK063), so whether the coherence threshold was ever
    validated leaves no trace in this repository.
    """
    import json as _json
    import random as _random

    if not corpus.exists():
        _note(f"{corpus} does not exist")
        raise typer.Exit(EXIT_REFUSED)

    records = [_json.loads(line) for line in corpus.read_text().splitlines() if line.strip()]
    if not records:
        _note(f"{corpus} contains no records")
        raise typer.Exit(EXIT_REFUSED)

    chosen = _random.Random(seed).sample(records, min(n, len(records)))
    lines = [
        _json.dumps(
            {
                "record_id": record["record_id"],
                "record_index": record["record_index"],
                "subdomain": record["subdomain"],
                "scenario": record["scenario"],
                "metadata": record["metadata"],
                "turns": record["turns"],
                "coherence_score": record["quality"]["coherence_score"],
                "rubric_id": record["quality"]["rubric_id"],
                # Fill these in, then run `ticket-dataset calibrate`. Left explicitly null rather
                # than absent so a partially scored sample is visible rather than silently
                # measuring a subset.
                "human_score": None,
                "human_criteria": {},
            },
            ensure_ascii=False,
        )
        for record in chosen
    ]
    rendered = "\n".join(lines) + "\n"
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered)
        _note(f"wrote {len(chosen)} records to {out}")
    else:
        print(rendered, end="")
    raise typer.Exit(EXIT_OK)


@app.command("calibrate")
def calibrate_command(
    sample: Annotated[Path, typer.Argument(help="A sample with human_score filled in.")],
    reviewer: Annotated[str, typer.Option("--by", help="Who did the scoring. Recorded.")],
    rubric: Annotated[Path, typer.Option(help="The rubric the judge used.")] = Path(
        "prompts/coherence-rubric.md"
    ),
    threshold: Annotated[
        float, typer.Option(help="The gate the comparison is judged against.")
    ] = 0.8,
    seed: Annotated[int | None, typer.Option(help="The seed the sample was drawn with.")] = None,
    out: Annotated[Path, typer.Option(help="Where the calibration record is written.")] = Path(
        "calibration"
    ),
    notes: Annotated[str, typer.Option(help="What you concluded.")] = "",
) -> None:
    """Compare a hand-scored sample against the judge and record what it showed (SC-011).

    Calibration is a human act; this does the arithmetic around it and leaves evidence that
    survives the session — which rubric was judged, which sample, by whom, and what was found.

    Two numbers, because they answer different questions. **Gate agreement** is whether the judge
    and the reviewer make the same admit/reject decision at the threshold, which is what the
    threshold is for. **Rank correlation** is whether the judge orders conversations the way a
    person does: a uniformly generous judge that ranks correctly can be fixed by moving the
    threshold; one that ranks badly cannot.
    """
    from ticket_dataset.generation.rubric import load_rubric
    from ticket_dataset.run.calibration import (
        assert_sample_matches_rubric,
        calibrate,
        load_scored_sample,
    )

    if not sample.exists():
        _note(f"{sample} does not exist")
        raise typer.Exit(EXIT_REFUSED)
    try:
        loaded_rubric = load_rubric(rubric)
        records = load_scored_sample(sample)
    except (TicketDatasetError, ValueError, json.JSONDecodeError) as error:
        _note(str(error))
        raise typer.Exit(EXIT_REFUSED) from error

    if not records:
        _note(f"{sample} contains no scored records")
        raise typer.Exit(EXIT_REFUSED)

    try:
        assert_sample_matches_rubric(records, loaded_rubric.rubric_id)
    except ValueError as error:
        _note(str(error))
        raise typer.Exit(EXIT_REFUSED) from error

    record = calibrate(
        records,
        rubric_id=loaded_rubric.rubric_id,
        rubric_sha256=loaded_rubric.sha256,
        threshold=threshold,
        reviewer=reviewer,
        corpus=str(sample),
        sample_seed=seed,
        notes=notes,
    )
    written = record.write(out)

    print(json.dumps(record.as_dict(), indent=2, sort_keys=True))
    _note(f"calibration of {record.rubric_id} against {record.sample_size} records by {reviewer}")
    _note(f"  gate: {record.gate_agreement_detail}")
    if record.rank_correlation is None:
        # The v1 failure: a judge returning one number has no ordering to correlate.
        _note("  rank: undefined — one side gave every record the same score")
    else:
        _note(f"  rank: rho {record.rank_correlation:+.2f}")
    _note(
        f"  spread: judge used {record.judge_spread['distinct']} distinct scores, "
        f"reviewer {record.human_spread['distinct']}"
    )
    _note(f"  wrote {written}")
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
