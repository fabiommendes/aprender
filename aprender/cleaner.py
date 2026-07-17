from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, assert_never, cast

from .types import JSON, Cell, QuestionId, QuestionType
from .yaml import dumps

type StructuredAnswer = str | list[str] | dict[str, str | None] | None

MULTIPLE_CHOICE_LENGTH_THRESHOLD = 50
MAX_MULTIPLE_CHOICES = 10

MAX_ASSOCIATION_CHOICES = 20
MAX_ASSOCIATION_TARGETS = 20

MAX_NUMBER_OF_FILL_IN_CHOICES = 10
ESSAY_QUESTION_NUMBER_OF_LINES_THRESHOLD = 20
ESSAY_MIN_UNIQUE_THRESHOLD = 15
ESSAY_MIN_UNIQUE_FRACTION_THRESHOLD = 0.75

CLOZE_REGEX: re.Pattern = re.compile(r"\{(?P<choice>[^{}]*)\}\s*|(?P<invalid>.+)")
MULTIPLE_SELECTION_SEPARATOR = re.compile(r"\n\s*;\s?")
ASSOCIATION_ITEM = re.compile(r"(?P<lhs>(.|\n)+?)(\n\ *-> *(?P<rhs>.+))?")

EMPTY_ASSOCIATION = "nenhuma opção correspondente"

TRANSLATE_TABLE = str.maketrans(
    {
        #
        # # Unicode space salad (https://jkorpela.fi/chars/spaces.html)
        #
        # " ": " ",  # SPACE; width = 1/4 em
        "\u00a0": " ",  # NO-BREAK SPACE; As a space, but often not adjusted by
        "\u1680": "-",  # OGHAM SPACE MARK;	Unspecified; usually not really a space but a dash
        "\u180e": "",  # MONGOLIAN VOWEL SEPARATOR	width=0
        "\u2000": "  ",  # EN QUAD;	width = 1 en (= 1/2 em)
        "\u2001": "    ",  # EM QUAD; width = 1 em (nominally, the height of the font)
        "\u2002": "  ",  # EN SPACE (nut); width = 1 en (= 1/2 em)
        "\u2003": "    ",  # EM SPACE (mutton); width = 1 em
        "\u2004": " ",  # THREE-PER-EM SPACE (thick space);	width = 1/3 em
        "\u2005": "  ",  # FOUR-PER-EM SPACE (mid space);	width = 1/4 em
        "\u2006": " ",  # SIX-PER-EM SPACE; width = 1/6 em
        "\u2007": " ",  # FIGURE SPACE;	“Tabular width”, the width of digits
        "\u2008": " ",  # PUNCTUATION SPACE; width = The width of a period “.”
        "\u2009": " ",  # THIN SPACE; width = 1/5 em (or sometimes 1/6 em)
        "\u200a": " ",  # HAIR SPACE; width = Narrower than THIN SPACE
        "\u200b": "",  # ZERO WIDTH SPACE; width = 0
        "\u202f": " ",  # NARROW NO-BREAK SPACE; width = Narrower than NO-BREAK SPACE (or SPACE), “typically the width of a thin space or a mid space”
        "\u205f": " ",  # MEDIUM MATHEMATICAL SPACE; width = 4/18 em
        "\u3000": " ",  # IDEOGRAPHIC SPACE; width = The width of ideographic (CJK) characters.
        "\ufeff": "",  # ZERO WIDTH NO-BREAK SPACE; width = 0
        #
        # Visible spaces
        #
        "\u2423": " ",  # OPEN BOX; visible symbol for SPACE
        "\u2422": " ",  # BLANK SYMBOL; visible symbol for SPACE
        "\u2420": " ",  # SYMBOL FOR SPACE; visible symbol for SPACE
        #
        # Line breaks
        #
        "\r": "\n",  # CARRIAGE RETURN; newline in Windows-style line breaks. Keep only \n
        "\u000b": "\n",  # LINE TABULATION; a vertical tab, treated as a line break in many contexts
        "\u000c": "\n",  # FORM FEED; a page break
        "\u0085": "\n",  # NEXT LINE;
        "\u2028": "\n",  # LINE SEPARATOR;
        "\u2029": "\n",  # PARAGRAPH SEPARATOR;
    }
)


def clean_responses(
    data: list[list[Cell]], types: dict[QuestionId, QuestionType] | None = None
) -> dict[str, JSON]:
    """
    Clean the given assignment **inplace**.

    It removes most Moodle-specific idiosyncrasies, such as strange unicode
    characters, and empty questions and responses.
    """
    if not data:
        return {}

    types = types or {}
    n_columns = max(map(len, data))

    columns = [[] for _ in range(n_columns)]
    for row in data:
        for i, cell in enumerate(row):
            columns[i].append(cell)

    questions: dict[QuestionId, JSON] = {}

    for i, col in enumerate(columns):
        id = f"q{i + 1}"
        if id in types:
            question_type = types[id]
        else:
            question_type = infer_question_type(id, col)

        structured = []
        for j, cell in enumerate(col):
            parsed = normalize_response(cell, question_type)
            structured.append(parsed)
            data[j][i] = render_structured(parsed)

        questions[id] = question_from_responses(question_type, structured)

    return questions


def normalize_string(s: str) -> str:
    return s.translate(TRANSLATE_TABLE)


def infer_question_type(question_id: QuestionId, answers: list[Cell]) -> QuestionType:
    answers_set = set([cast(str, answer) for answer in answers if answer])
    non_empty_answers = [
        answer for answer in answers if isinstance(answer, str) and answer.strip()
    ]

    if is_cloze_question(question_id, answers_set):
        return "fill-in"  # type: ignore

    if is_probable_multiple_selection_question(question_id, answers_set):
        return "multiple-selection"  # type: ignore

    if is_probable_association_question(question_id, answers_set):
        return "association"  # type: ignore

    if is_probable_essay_question(
        question_id,
        answers=non_empty_answers,
        answers_set=answers_set,
    ):
        return "text"

    if is_probable_multiple_choice_question(
        question_id,
        answers=non_empty_answers,
        answers_set=answers_set,
    ):
        return "multiple-choice"  # type: ignore

    return "text"


def is_cloze_question(question_id: QuestionId, answers: Iterable[str]) -> bool:
    # A cloze question is a question where the answer contains multiple parts,
    # usually separated by newlines or some other delimiter. Moodle renders each
    # option inside curly brackets and we can check this with an regex.
    for answer in answers:
        for match in CLOZE_REGEX.finditer(answer):
            if match.group("invalid"):
                return False
    return True


def is_probable_multiple_choice_question(
    question_id: QuestionId,
    answers: list[str],
    answers_set: set[str],
) -> bool:
    # A multiple-choice question is likely if there are only a few unique answers,s
    # and they are relatively short (e.g., "A", "B", "True", "False", "Paris").
    if not all(
        len(answer) <= MULTIPLE_CHOICE_LENGTH_THRESHOLD for answer in answers_set
    ):
        return False

    unique_answers = set(answers)
    if len(unique_answers) > MAX_MULTIPLE_CHOICES:
        return False

    return len(unique_answers) / len(answers) <= 0.5


def is_probable_essay_question(
    question_id: QuestionId,
    answers: list[str],
    answers_set: set[str],
) -> bool:
    # An essay question is likely if there are many unique answers, and they are relatively long.
    if any(
        len(answer.splitlines()) > ESSAY_QUESTION_NUMBER_OF_LINES_THRESHOLD
        for answer in answers_set
    ):
        return True

    n_answers = len(answers)
    n_unique = len(answers_set)
    if n_answers == n_unique or (
        n_unique >= ESSAY_MIN_UNIQUE_FRACTION_THRESHOLD * n_answers
        and n_unique >= ESSAY_MIN_UNIQUE_THRESHOLD
    ):
        return True

    return False


def is_probable_multiple_selection_question(
    question_id: QuestionId,
    answers_set: set[str],
) -> bool:
    # The list of options in a multiple-selection question is separated by
    # new lines and semicolons.
    has_multiple = False
    unique_choices: set[str] = set()

    for answer in answers_set:
        choices = MULTIPLE_SELECTION_SEPARATOR.split(answer)

        if len(choices) > 1:
            has_multiple = True
            if len(unique_choices) > MAX_MULTIPLE_CHOICES:
                return False

        unique_choices.update(choices)

    return has_multiple and len(unique_choices) <= MAX_MULTIPLE_CHOICES


def is_probable_association_question(
    question_id: QuestionId,
    answers_set: set[str],
) -> bool:
    # The list of options in an association question is separated by
    # new lines and arrows (e.g., "Paris -> France").
    unique_choices: set[str] = set()
    unique_sources: set[str] = set()

    for answer in answers_set:
        parts = answer.split("; ")
        if parts and parts[-1] == "":
            parts.pop()

        for item in parts:
            m = ASSOCIATION_ITEM.match(item)
            if not m:
                return False

            unique_choices.add(m.group("rhs"))
            unique_sources.add(m.group("lhs"))

            if (
                len(unique_choices) > MAX_ASSOCIATION_CHOICES
                or len(unique_sources) > MAX_ASSOCIATION_TARGETS
            ):
                return False

    return len(unique_choices) >= 2 and len(unique_sources) >= 2


def normalize_response(content: Cell, question_type: QuestionType) -> StructuredAnswer:
    if content is None:
        return None
    elif isinstance(content, datetime):
        return content.isoformat()
    elif not isinstance(content, str):
        return str(content)
    elif isinstance(content, str):
        content = normalize_string(content)

    match question_type:
        case "multiple-choice":
            return content.strip()

        case "multiple-selection":
            return MULTIPLE_SELECTION_SEPARATOR.split(content)

        case "fill-in":
            return [match.group("choice") for match in CLOZE_REGEX.finditer(content)]

        case "association":
            associations = {}
            if not content:
                return associations

            for item in content.split("; "):
                key, _, rhs = item.partition("\n -> ")
                if key and rhs:
                    key = key.strip().replace("\n", "<br>")
                    value = rhs.strip().replace("\n", "<br>")
                    associations[key] = value
            return associations

        case _:
            return normalize_string(content)


def render_structured(content: StructuredAnswer) -> str:
    if content is None:
        return ""
    elif isinstance(content, str):
        return content
    elif isinstance(content, (list, dict)):
        return dumps(content)
    else:
        raise TypeError(f"Unexpected type, got {type(content).__name__}")


def question_from_responses(
    question_type: QuestionType, responses: list[StructuredAnswer]
) -> JSON:
    """
    Infer the question type and create a Question object from the given responses.
    """

    base: dict[str, JSON] = {
        "type": question_type,
    }

    match question_type:
        case "multiple-choice":
            choices = set(k for k in responses if isinstance(k, str) and k)
            base["choices"] = sorted(choices)

        case "multiple-selection":
            choices = set()
            for response in responses:
                if isinstance(response, list):
                    choices.update(k for k in response if isinstance(k, str) and k)
            base["choices"] = sorted(choices)

        case "fill-in":
            choices = []
            for response in responses:
                if not isinstance(response, list):
                    continue
                for i, response in enumerate(response):
                    if response and i >= len(choices):
                        choices.append(set())
                    if response:
                        choices[i].add(response)
            base["choices"] = [
                sorted(c) if len(c) <= MAX_NUMBER_OF_FILL_IN_CHOICES else None
                for c in choices
            ]

        case "association":
            choices = set()
            targets = set()
            for response in responses:
                if not isinstance(response, dict):
                    continue
                choices.update(k for k in response.keys() if k)
                targets.update(v for v in response.values() if isinstance(v, str) and v)
            base["choices"] = sorted(choices)
            base["responses"] = sorted(targets)

        case "text":
            ...

        case _:
            assert_never(question_type)

    return base


def indent(src: str) -> str:
    return "\n".join("    " + line for line in src.splitlines())
