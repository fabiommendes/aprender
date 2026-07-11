from __future__ import annotations

from pathlib import Path

from .models import GenericQuestion, Quiz, Response, Submission


def db_to_assignment(db: Db, base_path: Path) -> list[Quiz]:
    """
    Transform the given database into a Chalk assignment.
    """
    assignments: list[Quiz] = []

    for exam in db["exams"]:
        id = slug(exam["exam"])
        assignment = Quiz(
            id=id,
            submissions={
                student_id: Submission(
                    start=response["started"],
                    end=response["completed"],
                    duration=response["duration"],
                    responses={
                        question_id: Response(
                            grade=answer["value"],
                            answer=answer["content"],
                        )
                        for question_id, answer in response["answers"].items()
                    },
                )
                for student_id, response in exam["responses"].items()
            },
            questions={
                question_id: GenericQuestion.model_validate(
                    {
                        "id": question_id,
                        "value": question["grade"],
                    }
                )
                for question_id, question in exam["questions"].items()
            },
        )
        assignments.append(assignment)
    return assignments


def slug(text: str) -> str:
    """
    Convert the given text to a slug.
    """
    return text.lower().replace(" ", "_").replace("/", "_")
