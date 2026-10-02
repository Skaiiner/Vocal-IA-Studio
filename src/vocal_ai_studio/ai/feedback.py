from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Exercise:
    title: str
    description: str

    def to_dict(self) -> dict:
        return {"title": self.title, "description": self.description}

    @staticmethod
    def from_dict(d: dict) -> "Exercise":
        return Exercise(d["title"], d["description"])


@dataclass
class CoachFeedback:
    summary: str
    strengths: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    exercises: list[Exercise] = field(default_factory=list)
    generated_by: str = "Reglas locales"

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "strengths": self.strengths,
            "issues": self.issues,
            "exercises": [e.to_dict() for e in self.exercises],
            "generated_by": self.generated_by,
        }

    @staticmethod
    def from_dict(d: dict) -> "CoachFeedback":
        return CoachFeedback(
            summary=d["summary"],
            strengths=list(d.get("strengths", [])),
            issues=list(d.get("issues", [])),
            exercises=[Exercise.from_dict(e) for e in d.get("exercises", [])],
            generated_by=d.get("generated_by", "Reglas locales"),
        )
