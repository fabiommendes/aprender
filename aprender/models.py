from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

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


#
# Models
#
class Title(BaseModel):
    course: str
    quiz: str | None
    role: Literal["response", "grade", "roster"]
