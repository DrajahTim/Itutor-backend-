"""
Generates a multiple-choice quiz from a CourseDocument's content using
the LLM (via Groq), then saves it as completely normal Quiz/Question
rows — reusing the exact same grading, Attempt, and mastery-tracking
pipeline that already exists for admin-authored quizzes.
"""
import json

from decouple import config
from groq import Groq

from learning.models import Question, Quiz

from .rag_service import GROQ_MODEL

REQUIRED_QUESTION_KEYS = {
    "text", "option_a", "option_b", "option_c", "option_d", "correct_option"
}
# `explanation` is requested from the model but treated as optional when
# saving — if the model omits it, we still create the question rather
# than failing the whole generation over a missing rationale.


class QuizGenerationError(Exception):
    pass


def build_generation_prompt(document_text: str, num_questions: int) -> str:
    # Truncate very long documents — sending an entire textbook chapter
    # isn't necessary for generating a handful of questions, and keeps
    # the request within reasonable token limits.
    excerpt = document_text[:8000]

    return (
        f"Based on the following study material, generate exactly "
        f"{num_questions} multiple-choice questions to test understanding "
        f"of the content. Each question must have exactly 4 options and "
        f"one correct answer.\n\n"
        f"Respond with ONLY valid JSON, no other text, in this exact format:\n"
        f'{{"questions": [{{"text": "question here", "option_a": "...", '
        f'"option_b": "...", "option_c": "...", "option_d": "...", '
        f'"correct_option": "A", "explanation": "one concise sentence on '
        f'why the correct option is right"}}]}}\n\n'
        f"correct_option must be exactly one of: A, B, C, D.\n"
        f"explanation must be a single concise sentence grounded in the "
        f"study material, explaining why the correct option is correct.\n\n"
        f"Study material:\n{excerpt}"
    )


def generate_quiz_from_document(document, num_questions: int = 5) -> Quiz:
    if not document.raw_text.strip():
        raise QuizGenerationError(
            "This document has no extracted text to generate questions from."
        )

    prompt = build_generation_prompt(document.raw_text, num_questions)

    client = Groq(api_key=config("GROQ_API_KEY"))
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        # Forces the model to return valid JSON rather than free text —
        # the single most important guardrail for reliable parsing.
        response_format={"type": "json_object"},
    )

    raw_content = response.choices[0].message.content

    try:
        parsed = json.loads(raw_content)
    except (json.JSONDecodeError, TypeError):
        raise QuizGenerationError("The generated response wasn't valid JSON.")

    questions_data = parsed.get("questions")
    if not questions_data or not isinstance(questions_data, list):
        raise QuizGenerationError("No questions were generated.")

    # Validate every question BEFORE creating anything in the database —
    # avoids ending up with a half-created quiz if one question is malformed.
    for q in questions_data:
        if not REQUIRED_QUESTION_KEYS.issubset(q.keys()):
            raise QuizGenerationError("A generated question was missing required fields.")
        if q["correct_option"] not in ("A", "B", "C", "D"):
            raise QuizGenerationError("A generated question had an invalid correct_option.")

    quiz = Quiz.objects.create(
        topic=document.topic,
        title=f"{document.title} — Quiz",
        passing_score=60,
    )

    for q in questions_data:
        Question.objects.create(
            quiz=quiz,
            text=q["text"],
            option_a=q["option_a"],
            option_b=q["option_b"],
            option_c=q["option_c"],
            option_d=q["option_d"],
            correct_option=q["correct_option"],
            # Optional — fall back to empty string if the model didn't
            # supply one, so a missing rationale never breaks generation.
            explanation=q.get("explanation", "") or "",
            source="generated",
        )

    return quiz