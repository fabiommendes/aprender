from __future__ import annotations

import builtins
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any, assert_never, cast, get_args

import rich
from typer import Argument, Option, Typer

from .types import JSON, QuestionId, QuestionType
from .yaml import dump

VALID_QUESTION_TYPES: set[QuestionType] = set(get_args(QuestionType))

app = Typer()


@app.command()
def load(
    path: Annotated[
        Path,
        Argument(
            metavar="PATH",
            help="Path to the HTML file to process",
        ),
    ],
    id: Annotated[
        str | None,
        Argument(
            metavar="ID",
            help="ID of the resulting resource",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        Option(
            ...,
            "--dry-run",
            "-d",
            help="Dump results to stdout instead of writing to files",
        ),
    ] = False,
    remove: Annotated[
        bool,
        Option(
            ...,
            "--remove",
            "-r",
            help="Remove original HTML files after processing",
        ),
    ] = False,
    force: Annotated[
        bool,
        Option(
            ...,
            "--force",
            "-f",
            help="Force overwrite of existing files",
        ),
    ] = False,
    question_type_specs: Annotated[
        list[str] | None,
        Option(
            ...,
            "--type",
            "-t",
            metavar="TYPE=QUESTIONS",
            help="Specify question types in the format TYPE=QUESTION for each question (e.g., -t text=q1,q2)",
        ),
    ] = None,
    email_id: Annotated[
        bool,
        Option(
            ...,
            "--email-id",
            help="Use email as the student ID",
        ),
    ] = False,
    suffix: Annotated[
        str | None,
        Option(
            ...,
            "--suffix",
            "-s",
            help="Suffix to append to output files (e.g., -s _v2)",
        ),
    ] = None,
) -> None:
    """
    Load Moodle-generated HTML tables describing students' responses and grades, and convert them to YAML format.
    """
    from .parser import parse_html

    if not path.is_file():
        raise ValueError(f"{path} is not a file")

    question_types = validate_question_type_specs(question_type_specs)
    parsed = parse_html(
        path.read_text(),
        id=id,
        question_types=question_types,
        email_id=email_id,
    )
    extra: Path | None = None
    if suffix:
        suffix = f"-{suffix.removeprefix('-')}"
    else:
        suffix = ""

    match parsed.role:
        case "response":
            main = Path(f"submissions{suffix}.csv")
            extra = Path(f"conf{suffix}.yaml")
        case "grade":
            main = Path(f"grades{suffix}.csv")
        case "roster":
            main = Path(f"roster{suffix}.csv")
        case other:
            assert_never(other)

    if not dry_run and not force and main.exists():
        msg = "Output files already exist. Use --force/-f to overwrite"
        rich.print(f"[red bold]Error[/]: {msg}", file=sys.stderr)
        raise exit(1)

    fd = sys.stdout if dry_run else main.open("w")
    parsed.table.write_csv(fd)
    del fd

    if extra and dry_run:
        print("---")
    if extra and parsed.json:
        if Path("grades.csv").exists():
            estimate_grades(parsed.json, Path("grades.csv"))
        questions: Any = parsed.json
        data = {"questions": [{"id": qid, **qdata} for qid, qdata in questions.items()]}
        if not extra.exists():
            dump(data, sys.stdout if dry_run else extra.open("w"))

    if not dry_run and remove:
        path.unlink()


def main():
    app()


def _debug(*args, **kwargs):
    if not args:
        args = (sys._getframe(1).f_locals,)  # type: ignore
    rich.print(*args, **kwargs)


def validate_question_type_specs(
    question_type_specs: list[str] | None,
) -> dict[QuestionId, QuestionType]:
    """
    Validate the --type option specifications and return a mapping of question
    IDs to their corresponding question types.
    """

    question_types: dict[QuestionId, QuestionType] = {}
    for spec in question_type_specs or []:
        try:
            question_type, sep, question_ids = spec.partition("=")
            if sep != "=":
                rich.print(f"[red]Invalid question type format:[/] {spec}")
                rich.print("[b]Expected TYPE=QUESTION_ID1,QUESTION_ID2,...[/]")
                exit(1)
            elif question_type not in VALID_QUESTION_TYPES:
                msg = f"[red]Invalid question type: {question_type} (must be one of {', '.join(VALID_QUESTION_TYPES)})[/red]"
                rich.print(msg)
                exit(1)

            for question_id in question_ids.split(","):
                question_types[question_id] = cast(QuestionType, question_type)

        except ValueError:
            raise SystemExit(f"Invalid question type format: {spec}")
    return question_types


builtins.dbg = _debug  # type: ignore


def estimate_grades(json: dict[str, JSON], grades_csv_path: Path) -> None:
    """
    Estimate grades based on the provided JSON data and update the grades CSV file.
    """
    import csv

    if not grades_csv_path.exists():
        return

    grades = defaultdict(Decimal)
    with grades_csv_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        columns = list(reader.fieldnames or [])
        if not columns:
            return

        for row in reader:
            del row["id"]
            row.pop("email", None)

            for id, value in row.items():
                try:
                    number = Decimal(value)
                except (ValueError, InvalidOperation):
                    continue
                grades[id] = max(grades[id], number)

    for id, question in json.items():
        if not isinstance(question, dict):
            continue
        if id in grades:
            question["value"] = str(grades[id])
