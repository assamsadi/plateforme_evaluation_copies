"""
Test d'intégration RÉEL — ArbitrationService.resolve_correction() contre une
vraie DB (pas de mock, contrairement à tests/unit/services/test_arbitration_
service.py).

RÉÉCRIT (2026-08-18) — ce fichier documentait à l'origine un trou
d'architecture réel : Submission.status restait bloqué à PENDING_ARBITRATION
pour toujours après résolution, `teacher_arbitration_node` n'existant pas
(0 octet). Ce nœud est désormais construit (cf. app/graph/nodes/teacher_
arbitration_node.py, app/graph/routing.py, app/graph/pipeline_graph.py) et
ArbitrationService.resolve_correction() déclenche désormais la reprise —
ce test vérifie la NOUVELLE transition réelle plutôt que l'ancien constat de
blocage (cf. l'ancienne docstring de ce fichier, qui prévenait explicitement
qu'une réécriture serait nécessaire le jour où ce trou serait comblé).

process_arbitration_resolved.delay(...) est mocké (jamais un vrai appel
Celery dans ce test — même discipline que les tests Kafka de ce projet,
cf. test_evaluation_node_kafka_notification.py) : ce test vérifie que le
DÉCLENCHEMENT a bien lieu (et avec le bon submission_id), pas que la reprise
LangGraph elle-même s'exécute jusqu'au bout (ça, c'est le rôle d'un futur
test bout-en-bout du graph complet, hors périmètre ici — câblage service
uniquement).

Couvre aussi le cas à PLUSIEURS ExtractionCorrection AMBIGUËS sur la même
soumission (cf. docstring has_pending_for_submission) : la reprise ne doit
JAMAIS se déclencher tant qu'il en reste au moins une PENDING.
"""
import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.domain.models.academic.group import Group
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.correction_arbitration import (
    ArbitrationStatus,
    ArbitrationVerdict,
    CorrectionArbitration,
)
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.extraction_correction import (
    ContestationStatus,
    ExtractionContentType,
    ExtractionCorrection,
    ExtractionEvidenceLevel,
)
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.models.shared.constants import CONTESTATION_RESOLVED_CONFIDENCE_SCORE
from app.domain.repositories.correction_arbitration_repository import (
    SQLAlchemyCorrectionArbitrationRepository,
)
from app.domain.repositories.extraction_correction_repository import (
    SQLAlchemyExtractionCorrectionRepository,
)
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.services.arbitration_service import ArbitrationService


def _make_correction(submission_id: uuid.UUID, label: str) -> ExtractionCorrection:
    return ExtractionCorrection(
        submission_id=submission_id, question_id=None,
        image_crop_path=f"crops/{label}.png", page_number=1,
        content_type=ExtractionContentType.TEXT,
        prediction_ocr=f"Résultat OCR original ({label}).",
        human_correction=f"Version réclamée par l'étudiant ({label}).",
        confidence_score=Decimal("0.500"), bounding_box={"x": 0, "y": 0, "width": 10, "height": 10},
        evidence_level=ExtractionEvidenceLevel.LABEL_EXPLICITE,
        contestation_status=ContestationStatus.AMBIGU,
    )


async def _seed_submission_with_ambiguous_corrections(db_session, correction_count: int):
    user_repo = SQLAlchemyUserRepository(db_session)

    prog = Program(name=f"Prog_{uuid.uuid4()}", code=f"P_{uuid.uuid4()}"[:10])
    db_session.add(prog)
    await db_session.flush()

    group = Group(program_id=prog.id, label="G1", academic_year="2024-2025")
    module = Module(program_id=prog.id, name=f"Mod_{uuid.uuid4()}", code=f"M_{uuid.uuid4()}"[:10])
    db_session.add_all([group, module])
    await db_session.flush()

    professor = await user_repo.create_professor(
        email=f"prof_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Prof", last_name="Arbitre", department="Info", title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )
    student = await user_repo.create_student(
        email=f"stu_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Bob", last_name="Contestataire", student_number=f"STU_{uuid.uuid4()}"[:20],
        group_id=group.id, enrollment_year=2024, level="L3",
    )
    exercise = Exercise(
        module_id=module.id, created_by_professor_id=professor.id,
        title="Exercice arbitrage", status=ExerciseStatus.PUBLISHED_AS_HOMEWORK,
    )
    db_session.add(exercise)
    await db_session.flush()

    submission = Submission(
        exercise_id=exercise.id, student_id=student.id, attempt_number=1,
        status=SubmissionStatus.PENDING_ARBITRATION, document_path="x",
        document_mime_type="application/pdf",
    )
    db_session.add(submission)
    await db_session.flush()

    corrections = [_make_correction(submission.id, f"block{i}") for i in range(correction_count)]
    db_session.add_all(corrections)
    await db_session.flush()

    # §2 étape 6 — même précondition que le vrai flux (contestation_
    # verification_service._persist_verdict) : les lignes PENDING existent
    # déjà AVANT que le professeur ne résolve quoi que ce soit.
    arbitrations = [
        CorrectionArbitration(extraction_correction_id=c.id, status=ArbitrationStatus.PENDING)
        for c in corrections
    ]
    db_session.add_all(arbitrations)
    await db_session.flush()

    return professor, submission, corrections


def _make_service(db_session) -> ArbitrationService:
    return ArbitrationService(
        arbitration_repo=SQLAlchemyCorrectionArbitrationRepository(db_session),
        incident_repo=None,  # jamais consulté par resolve_correction — inutile de le construire ici.
        submission_repo=SQLAlchemySubmissionRepository(db_session),
        integrity_repo=None,  # idem.
        user_repo=SQLAlchemyUserRepository(db_session),
        extraction_correction_repo=SQLAlchemyExtractionCorrectionRepository(db_session),
        exercise_repo=None,  # jamais consulté par resolve_correction — inutile de le construire ici.
    )


@pytest.mark.anyio
async def test_resolve_correction_updates_extraction_and_unblocks_submission(db_session):
    """Cas nominal — une seule ExtractionCorrection AMBIGUË sur la soumission."""
    professor, submission, corrections = await _seed_submission_with_ambiguous_corrections(
        db_session, correction_count=1,
    )
    correction = corrections[0]
    service = _make_service(db_session)

    claimed = "Version tranchée par le professeur, qui fait foi désormais."
    with patch("app.services.arbitration_service.process_arbitration_resolved.delay") as mock_delay:
        result = await service.resolve_correction(
            extraction_correction_id=correction.id,
            teacher_professor_id=professor.id,
            verdict=ArbitrationVerdict.ACCEPTED.value,
            comment="Réclamation de l'étudiant confirmée après relecture.",
            claimed_correction=claimed,
        )

    # 1. Le verdict est réellement persisté et correct.
    assert result.status == ArbitrationStatus.RESOLVED.value
    assert result.verdict == ArbitrationVerdict.ACCEPTED.value
    assert result.teacher_full_name == "Prof Arbitre"

    # 2. ExtractionCorrection réellement mis à jour en base (relecture forcée, pas l'objet Python en mémoire).
    await db_session.refresh(correction)
    assert correction.verified_content == claimed
    assert correction.contestation_status == ContestationStatus.RESOLVED
    assert correction.confidence_score == CONTESTATION_RESOLVED_CONFIDENCE_SCORE

    # 3. LE FIX — Submission.status débloqué (plus aucune arbitration PENDING).
    await db_session.refresh(submission)
    assert submission.status == SubmissionStatus.PENDING_EVALUATION

    # 4. La reprise du thread LangGraph a bien été déclenchée, avec le bon submission_id.
    mock_delay.assert_called_once_with(submission_id=str(submission.id))


@pytest.mark.anyio
async def test_resolve_correction_does_not_unblock_while_another_correction_still_pending(db_session):
    """
    Deux ExtractionCorrection AMBIGUËS sur la MÊME soumission — résoudre la
    première ne doit RIEN débloquer tant que la seconde reste PENDING.
    """
    professor, submission, corrections = await _seed_submission_with_ambiguous_corrections(
        db_session, correction_count=2,
    )
    first, second = corrections
    service = _make_service(db_session)

    with patch("app.services.arbitration_service.process_arbitration_resolved.delay") as mock_delay:
        await service.resolve_correction(
            extraction_correction_id=first.id,
            teacher_professor_id=professor.id,
            verdict=ArbitrationVerdict.ACCEPTED.value,
            comment="Première résolution.",
            claimed_correction="Version tranchée (1).",
        )
        await db_session.refresh(submission)
        assert submission.status == SubmissionStatus.PENDING_ARBITRATION, (
            "Ne doit pas débloquer tant que la 2e correction reste PENDING."
        )
        mock_delay.assert_not_called()

        # Résolution de la seconde -> plus aucune PENDING -> déblocage réel.
        await service.resolve_correction(
            extraction_correction_id=second.id,
            teacher_professor_id=professor.id,
            verdict=ArbitrationVerdict.REJECTED.value,
            comment="Seconde résolution.",
            claimed_correction="Version tranchée (2).",
        )

    await db_session.refresh(submission)
    assert submission.status == SubmissionStatus.PENDING_EVALUATION
    mock_delay.assert_called_once_with(submission_id=str(submission.id))
