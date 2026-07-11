from __future__ import annotations

import locale
import re
from datetime import datetime
from decimal import Decimal
from functools import wraps
from typing import Any, Callable, Literal

from pydantic import BaseModel

type Cell = str | datetime | None | Decimal
type JSONAtom = str | int | float | bool | None
type JSON = JSONAtom | dict[str, Any] | list[Any]
type QuestionId = str
type StudentId = str
type Role = Literal["response", "grade"]
type QuestionType = Literal[
    "multiple-choice",
    "multiple-selection",
    "association",
    "text",
    "fill-in",
    "association",
]


#
# Constants
#
ROLE_TRANSLATIONS: dict[str, Role] = {
    "respostas": "response",
    "notas": "grade",
}


ROSTER_RE = re.compile(r"courseid_(\d+)_participants", re.IGNORECASE)
LANGS = {
    "pt-br": {
        "duration": r"(?P<minutes>\d{1,2})\s*(?:minutos)?\s*(?P<seconds>\d{1,2})?\s*(?:segundos)?",
        "date": "%d %B %Y  %H:%M",
    }
}


#
# Models
#
class Title(BaseModel):
    course: str
    quiz: str | None
    role: Literal["response", "grade", "roster"]


#
# Validator functions
#
def ensure_string[T](fn: Callable[[str], T]) -> Callable[[Any], T]:
    """
    Decorator to ensure that the input to the function is a string.
    Raises a ValueError if the input is not a string.
    """

    @wraps(fn)
    def wrapper(arg: Any) -> T:
        if not isinstance(arg, str):
            raise ValueError(f"Expected a string, got {type(arg).__name__}")
        return fn(arg)

    return wrapper


def nullable(fn: Callable[[Any], Any]) -> Callable[[Any], Any | None]:
    """
    Decorator to allow the function to return None if the input is None.
    """

    @wraps(fn)
    def wrapper(arg: Any) -> Any | None:
        if arg is None:
            return None
        return fn(arg)

    return wrapper


def type_or[Typ, T, R](
    typ: type[Typ],
) -> Callable[[Callable[[T], R]], Callable[[T | Typ], R | Typ]]:
    """
    Decorator to allow the function to accept a specific type or None.
    If the input is of the specified type, it will be passed to the function.
    If the input is None, the function will return None.
    Raises a ValueError if the input is neither of the specified type nor None.
    """

    def decorator(fn: Callable[[T], R]) -> Callable[[T | Typ], R | Typ]:
        @wraps(fn)
        def wrapper(arg: T | Typ) -> R | Typ:
            if isinstance(arg, typ):
                return arg
            return fn(arg)  # type: ignore

        return wrapper

    return decorator


#
# Validators
#
@ensure_string
def validate_title(title: str) -> Title:
    """
    Parse the title of the Moodle page to extract course, exam, and role information.
    """
    src = title
    if m := ROSTER_RE.fullmatch(src):
        course_id = m.group(1)
        return Title(course=f"Course {course_id}", quiz=None, role="roster")

    course, _, src = src.partition("-")
    if not course:
        raise ValueError(f"Invalid title format: {title}")

    exam, _, role = src.rpartition("-")
    if not exam or not role:
        raise ValueError(f"Invalid title format: {title}")

    return Title(
        course=course.strip(), quiz=exam.strip(), role=validate_role(role.strip())
    )


@ensure_string
def validate_role(role: str) -> Role:
    """
    Validate and normalize the role string to a standard format.
    """
    try:
        return ROLE_TRANSLATIONS[role.lower()]
    except KeyError:
        raise ValueError(f"Unknown role: {role}")


@ensure_string
def validate_student_id(email: str) -> StudentId:
    """
    Extract the student ID from an email address.
    """
    return email.split("@")[0]


@ensure_string
def validate_duration(duration: str) -> float | None:
    duration = duration.strip()
    if is_empty_cell(duration):
        return None

    if match := re.match(LANGS["pt-br"]["duration"], duration):
        minutes = int(match.group("minutes"))
        seconds = int(match.group("seconds") or 0)
        return round(minutes + seconds / 60, 2)
    raise ValueError(f"Invalid duration format: {duration}")


def validate_optional_date(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    elif not isinstance(value, str):
        raise ValueError(f"Expected a string or datetime, got {type(value).__name__}")

    if is_empty_cell(value):
        return None

    src = value.removesuffix("PM").removesuffix("AM").strip()
    locale.setlocale(locale.LC_TIME, "pt_BR.UTF-8")
    return datetime.strptime(src, LANGS["pt-br"]["date"])


def validate_content(content: str | None) -> str | None:
    if content is None:
        return None
    if not isinstance(content, str):
        raise ValueError(f"Expected a string or None, got {type(content).__name__}")
    content = content.strip()
    if not content or content in ("-", "n/a", "N/A"):
        return None
    return content


def validate_cell(content: Any) -> Cell:
    if content is None:
        return ""
    if isinstance(content, (int, float, str, Decimal)):
        return str(content)
    if isinstance(content, datetime):
        return content.isoformat()

    raise TypeError(f"Unexpected type, got {type(content).__name__}")


def render_cell(content: Cell) -> str:
    if content is None:
        return ""
    if isinstance(content, datetime):
        return content.isoformat()
    return str(content)


def validate_question_id(col: Any) -> QuestionId:
    """
    Extract the question ID from a column identifier.

    Question ids are strings like "q1", "q2", etc. If the column is an integer, we assume it's a question number and prefix it with "q".
    """
    if isinstance(col, int):
        return f"q{col}"
    elif not isinstance(col, str):
        raise ValueError(f"Invalid column type: {type(col).__name__}")
    return col


def validate_grade(value: Any) -> Decimal | None:
    if isinstance(value, (float, int, Decimal)):
        return Decimal(value)
    elif not isinstance(value, str):
        msg = f"Expected a string, float, int, or Decimal, got {type(value).__name__}"
        raise ValueError(msg)

    try:
        data = value.replace(",", ".")
        if data.lower() in ("", "-", "n/a", "na", "requer avaliação"):
            return None
        return Decimal(data)
    except ValueError:
        return None


#
# Utility functions
#
def is_empty_cell(content: str) -> bool:
    return content.strip() in ("", "-", "n/a", "N/A")
