"""
AgentExecutionContext = contexte d'exécution unifié transmis à tous les 11 agents AI.

Contient les métadonnées de traçabilité et de routage (submission_id, exercise_id,
trace_id, flow_type, user_id, db_session, metadata) sans polluer les signatures de méthodes.
"""
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class AgentExecutionContext:
    trace_id: str
    flow_type: Literal["exercise_setup", "student_evaluation"]
    submission_id: uuid.UUID | None = None
    exercise_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    db_session: Any = None
    metadata: dict = field(default_factory=dict)
