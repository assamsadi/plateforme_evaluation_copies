"""
Modèles et structures de données pour la boucle de rétroaction (Feedback Loop / Active Learning).
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class OCRFeedbackEntry:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    submission_id: uuid.UUID = field(default_factory=uuid.uuid4)
    original_text: str = ""
    corrected_text: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TeacherFeedbackEntry:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    evaluation_id: uuid.UUID = field(default_factory=uuid.uuid4)
    professor_id: uuid.UUID = field(default_factory=uuid.uuid4)
    original_grade: float = 0.0
    adjusted_grade: float = 0.0
    feedback_notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ArbitrationFeedbackEntry:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    arbitration_id: uuid.UUID = field(default_factory=uuid.uuid4)
    decision: str = ""
    reasoning_delta: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
