"""
Job = suit l'exécution du pipeline LangGraph pour LES DEUX flux
(exercise_setup et student_evaluation, §2 du résumé), y compris ses
interruptions HITL (current_node indique où : "student_verification",
"teacher_validation", "teacher_arbitration", etc.).

FK nullable double (pas de modèle polymorphe, §ce choix déjà justifié) :
exercise_id rempli SI flow_type == EXERCISE_SETUP, submission_id rempli
SI flow_type == STUDENT_EVALUATION — jamais les deux, jamais aucun.
Règle appliquée par le service, pas par une contrainte DB.

Enrichissements pour l'observabilité :
- priority : ordre d'exécution des jobs.
- retry_count : nombre de relances après échec.
- started_at / completed_at : temps réel d'exécution.
- execution_duration_ms : durée totale (Grafana/Prometheus).
- worker_id : worker Celery ayant exécuté le job.
- progress_percentage : progression globale du pipeline.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum as PgEnum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class JobFlowType(StrEnum):
    EXERCISE_SETUP = "exercise_setup"
    STUDENT_EVALUATION = "student_evaluation"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRYING = "retrying"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class Job(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "jobs"

    # thread_id LangGraph == Submission.id ou Exercise.id selon le flow_type
    # (déjà l'id de l'entité concernée) ; pas de colonne séparée nécessaire,
    # exercise_id/submission_id ci-dessous EST ce thread_id.
    exercise_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("exercises.id"), nullable=True
    )

    submission_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("submissions.id"), nullable=True
    )

    flow_type: Mapped[JobFlowType] = mapped_column(
        PgEnum(JobFlowType, name="job_flow_type"),
        nullable=False,
    )

    status: Mapped[JobStatus] = mapped_column(
        PgEnum(JobStatus, name="job_status"),
        nullable=False,
        default=JobStatus.PENDING,
    )

    priority: Mapped[JobPriority] = mapped_column(
        PgEnum(JobPriority, name="job_priority"),
        nullable=False,
        default=JobPriority.NORMAL,
    )

    current_node: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Nombre de tentatives (retry Celery/LangGraph)
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    # Début réel d'exécution
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Fin réelle d'exécution
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Durée totale d'exécution en millisecondes
    execution_duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # Worker Celery ayant exécuté le job
    worker_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # Progression globale du pipeline (0-100)
    progress_percentage: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    # Plafond d'appels LLM par thread (audit "garanties transverses", Plan
    # D) — remis à zéro à CHAQUE run (démarrage frais ou reprise), jamais
    # cumulatif à travers les reprises (cf. entry_router_node/job_tasks.py::
    # resume_thread, qui le remettent explicitement à 0 avant chaque
    # ainvoke()). Comparé à Settings.MAX_LLM_CALLS_PER_THREAD par
    # invoke_llm_with_fallback avant chaque tentative.
    llm_call_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )