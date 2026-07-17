from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from typing import IO, Callable, Iterator, Literal, NamedTuple, assert_never, cast

from bs4 import BeautifulSoup

from . import types as v
from .cleaner import clean_responses
from .constants import NORMALIZED_COLUMN_NAMES
from .types import (
    JSON,
    QuestionId,
    QuestionType,
    Title,
)

QUESTION_GRADE_COL_RE = re.compile(
    r"Q\.\s*(?P<question_id>\d+)\s*\/(?P<max_grade>\d+)", re.IGNORECASE
)


@dataclass
class Table:
    columns: list[str]
    data: list[Row]

    def iter_rows(self) -> Iterator[list[str]]:
        for cells, questions in self.data:
            row = [v.render_cell(cells.get(col)) for col in self.columns]
            row.extend(map(v.render_cell, questions))
            yield row

    def write_csv(self, file: IO[str]) -> None:
        n_questions = 0
        if self.data:
            n_questions = max(len(row.questions) for row in self.data)
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(self.columns + [f"q{i}" for i in range(1, n_questions + 1)])
        for row in self.iter_rows():
            writer.writerow(row)


class Row(NamedTuple):  # noqa: F821
    cells: dict[str, v.Cell]
    questions: list[v.Cell]


class Parsed(NamedTuple):
    id: str
    role: Literal["response", "grade", "roster"]
    table: Table
    json: dict[str, JSON] | None


def parse_html(
    data: BeautifulSoup | str,
    id: str | None = None,
    question_types: dict[QuestionId, QuestionType] = {},
    email_id: bool = False,
) -> Parsed:
    """
    Parse the given BeautifulSoup object to extract course, exam, and responses information.
    """

    soup = BeautifulSoup(data, "html.parser") if isinstance(data, str) else data
    title = parse_title_section(soup)
    if id is None and title.role in ("response", "grade"):
        id = "quiz"
    elif id is None:
        id = "roster"

    json = None
    match title.role:
        case "response":
            table, json = parse_submissions(soup, question_types)
        case "grade":
            table = parse_grades(soup, email_id=email_id)
        case "roster":
            table = parse_roster(soup)
        case other:
            assert_never(other)
            raise ValueError(f"Unknown role: {other}")

    return Parsed(id, title.role, table, json)


def parse_table(
    soup: BeautifulSoup,
    skip_last_row: bool = False,
    colmap: dict[str, Callable[[dict[str, str]], v.Cell]] = {},
    extramap: Callable[[str], v.Cell] = lambda x: x,
) -> Table:
    """
    Parse table from the given BeautifulSoup object.
    """

    table = soup.find("table")
    if table is None:
        raise ValueError("No table found in the HTML")

    head, *rows = table.find_all("tr")
    head_cells = head.find_all("th")
    if len(head_cells) < 2:
        raise ValueError("Table must have at least two columns")
    if skip_last_row:
        rows = rows[:-1]

    col_ids = [normalize_column(cell.text.strip()) for cell in head_cells]
    result: list[Row] = []

    for raw_cells in rows:
        tds = raw_cells.find_all("td")
        raw_cells = dict(zip(col_ids, [cast(str, cell.text.strip()) for cell in tds]))

        base_cells = {k: v for k, v in raw_cells.items() if isinstance(k, str)}
        fixed_cells = {k: colmap[k](base_cells) for k in colmap}

        extra_cells_ = sorted(
            (k, v) for k, v in raw_cells.items() if isinstance(k, int)
        )
        extra_cells = [extramap(v) for _, v in extra_cells_]

        result.append(Row(fixed_cells, extra_cells))

    return Table(
        columns=list(colmap),
        data=result,
    )


def parse_submissions(
    soup: BeautifulSoup,
    question_types: dict[QuestionId, QuestionType],
) -> tuple[Table, dict[str, JSON]]:
    """
    Parse the answers table from the given BeautifulSoup object.
    """
    parsed = parse_table(
        soup,
        skip_last_row=True,
        colmap={
            "id": lambda row: v.validate_student_id(row["email"]),
            "start": lambda row: v.validate_optional_date(row["started"]),
            "end": lambda row: v.validate_optional_date(row["completed"]),
        },
        extramap=v.validate_content,
    )
    data = [row.questions for row in parsed.data]
    json = clean_responses(data, question_types)
    return parsed, json


def parse_grades(soup: BeautifulSoup, email_id: bool = False) -> Table:
    """
    Parse the grades table from the given BeautifulSoup object.
    """
    if not email_id:
        id_getter = lambda row: v.validate_student_id(row["email"])
    else:
        id_getter = lambda x: x

    data = parse_table(
        soup,
        skip_last_row=True,
        colmap={
            "id": id_getter,
        },
        extramap=v.validate_grade,
    )
    return data


def parse_roster(soup: BeautifulSoup) -> Table:
    """
    Parse the roster table from the given BeautifulSoup object.
    """
    return parse_table(
        soup,
        skip_last_row=True,
        colmap={
            "id": lambda row: v.validate_student_id(row["email"]),
            "name": lambda row: row["first_name"] + " " + row["last_name"],
            "email": lambda row: row["email"],
            "email_alt": lambda row: row["email2"],
        },
        extramap=v.validate_grade,
    )


def parse_title_section(soup: BeautifulSoup) -> Title:
    """
    Parse the <title> tag of the page.
    """
    tag = soup.find("title")
    if tag is None:
        raise ValueError("No title found in the HTML")
    data = tag.text.strip()
    return v.validate_title(data)


def normalize_column(name: str) -> str | int:
    try:
        return NORMALIZED_COLUMN_NAMES[name]
    except KeyError:
        pass

    if m := QUESTION_GRADE_COL_RE.match(name):
        data = m.groupdict()
        return int(data["question_id"])

    name = name.lower().strip()
    parts = name.split()
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    return name.lower().replace(" ", "_")


def normalize_qid(qid: str) -> int | None:
    qid = qid.strip().lower().removeprefix("q")
    if not qid:
        return None
    if not qid.isdigit():
        return None
    return int(qid)
