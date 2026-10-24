"""
Service d'évaluation (notation) des soumissions.

Règles métier appliquées :
1. Une évaluation enregistre les critères classiques (méta-donnée
   informative, n'impacte plus la note — cf. point 4).
2. Le calcul de la note et sa persistance sont strictement séparés de tout
   calcul de compétence C2PCT (cf. point 6) — ce service est un persisteur
   de notes, jamais un agrégateur de compétences.
3. record_evaluation() refuse désormais toute évaluation d'une soumission
   PENDING_ARBITRATION (SubmissionPendingArbitrationError) — TODO résolu
   (§2 étape 6, doc Contestation_Verification_Agent : une copie encore
   incertaine ne doit jamais recevoir de note).

Phase 4/4 (chantier C2PCT, Pedagogical_Evaluation_Agent) :
4. record_question_score() : point d'intégration avec PedagogicalEvaluation
   Agent.evaluate_question() — accepte un QuestionScoreResult DÉJÀ CALCULÉ
   (l'agent calcule, ce service persiste, même principe que tout le reste
   de ce projet) et le traduit en un appel record_evaluation() avec une
   ligne EvaluationCriteria PAR COMPÉTENCE (competency_code +
   subquestion_detail JSONB, jamais une par sous-question).

Câblage copy_report (§0 Comparative_Evaluation_Agent) :
5. record_question_score() accepte désormais un QuestionReport optionnel
   (déjà assemblé par PedagogicalEvaluationAgent.build_question_report),
   persisté tel quel dans Evaluation.copy_report_detail (JSONB, PAR
   QUESTION — même granularité que cette table). get_copy_report(
   submission_id) agrège à la LECTURE les copy_report_detail de toutes les
   Evaluation d'une soumission en un CopyReport (avec overview) — même
   principe que get_total_score_for_submission (agrégat calculé, jamais un
   document stocké séparément).

Retrait du mécanisme Niveau 1 (Competency_Assessment_Agent, Partie 1/2) :
6. _compute_updated_mastery/_update_competency_profile_from_success_rate
   RETIRÉS (et competency_profile_repo avec eux) — ce mécanisme (moyenne
   mobile simple, par question, câblé au ticket précédent) aurait
   constitué une DEUXIÈME source de vérité concurrente pour
   StudentCompetencyProfile aux côtés de CompetencyAssessmentService
   (Niveau 2 pondéré par sous-questions réelles + Niveau 3 décroissance
   exponentielle configurable) — même anti-pattern déjà rejeté pour
   c2pct_observed (cf. ancien point 8, historique). Competency_Assessment_
   Agent/CompetencyAssessmentService est désormais l'UNIQUE écrivain de
   StudentCompetencyProfile. Ce service n'a donc plus AUCUNE connaissance
   des compétences C2PCT — un persisteur de notes générique.

Calcul de note classique (ticket dédié) :
7. record_question_score() accepte désormais aussi un
   ClassicQuestionScoreResult (PedagogicalEvaluationAgent.
   evaluate_question_classic(), mécanisme barème à critères, jamais le
   mécanisme C2PCT natif sur une même question) — une ligne
   EvaluationCriteria PAR CRITÈRE (criterion_id, famille déjà supportée par
   create_with_criteria/EvaluationCriteria, cf. leurs docstrings). Seule la
   construction de criteria_data diffère par type de résultat ; record_
   evaluation() reste le point de persistance UNIQUE pour les deux.
"""
import uuid
from decimal import Decimal
from typing import Protocol

from app.agents.Pedagogical_Evaluation_Agent import (
    ClassicQuestionScoreResult,
    CopyReport,
    QuestionReport,
    QuestionScoreResult,
)
from app.core.exceptions import (
    EvaluationNotFoundError,
    ExerciseNotFoundError,
    ForbiddenError,
    NotExerciseOwnerError,
    SubmissionNotFoundError,
    SubmissionPendingArbitrationError,
)
from app.domain.models.assessment.evaluation import Evaluation
from app.domain.models.assessment.exercise import Exercise
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.models.identity.user import User, UserRole
from app.domain.repositories.evaluation_repository import EvaluationRepositoryProtocol
from app.domain.repositories.exercise_repository import ExerciseRepositoryProtocol
from app.domain.repositories.extraction_correction_repository import (
    ExtractionCorrectionRepositoryProtocol,
)
from app.domain.repositories.reasoning_clarification_request_repository import (
    ReasoningClarificationRequestRepositoryProtocol,
)
from app.domain.repositories.pagination import DEFAULT_PAGE_SIZE, CursorPage
from app.domain.repositories.submission_repository import SubmissionRepositoryProtocol
from app.domain.repositories.user_repository import UserRepositoryProtocol
from app.infra_services.storage_service import StorageContainer, StorageService
from app.domain.schemas.evaluation_schemas import (
    EvaluationRead,
    QuestionResultRead,
    StudentModuleSummaryRead,
    SubmissionResultRead,
)
from app.domain.schemas.submission_schemas import SubmissionSummaryRead


def _to_evaluation_read(evaluation: Evaluation, question_order: int = 1) -> EvaluationRead:
    """Helper pour enrichir et sérialiser Evaluation en EvaluationRead."""
    if getattr(evaluation, "question_order", None) is None:
        evaluation.question_order = question_order
    if hasattr(evaluation, "criteria") and evaluation.criteria:
        for c in evaluation.criteria:
            if getattr(c, "criterion_label", None) is None:
                # Phase 4/4 — ligne compétence (criterion_id=None) : jamais
                # str(None)="None", criterion_label reste None (cf. schéma,
                # champ optionnel). Ligne classique : résolution héritée.
                criterion_id = getattr(c, "criterion_id", None)
                c.criterion_label = criterion_id if criterion_id is not None else None
    return EvaluationRead.model_validate(evaluation)


class EvaluationServiceProtocol(Protocol):
    async def record_evaluation(
        self,
        submission_id: uuid.UUID,
        question_id: uuid.UUID,
        score: Decimal,
        classic_criteria_observed: dict,
        criteria_data: list[dict],
        copy_report_detail: dict | None = None,
    ) -> EvaluationRead: ...

    async def record_question_score(
        self,
        submission_id: uuid.UUID,
        bareme_id: uuid.UUID | None,
        result: QuestionScoreResult | ClassicQuestionScoreResult,
        question_report: QuestionReport | None = None,
    ) -> EvaluationRead: ...

    async def get_total_score(self, submission_id: uuid.UUID) -> Decimal: ...
    async def list_evaluations(self, submission_id: uuid.UUID) -> list[EvaluationRead]: ...
    async def get_copy_report(self, submission_id: uuid.UUID) -> CopyReport: ...
    async def get_evaluation(
        self, evaluation_id: uuid.UUID, requesting_user: User
    ) -> EvaluationRead: ...
    async def list_evaluations_for_submission(
        self, submission_id: uuid.UUID, requesting_user: User
    ) -> list[EvaluationRead]: ...
    async def get_copy_report_for_professor(
        self, submission_id: uuid.UUID, requesting_professor_id: uuid.UUID
    ) -> CopyReport: ...
    async def get_results_for_student(
        self, submission_id: uuid.UUID, requesting_student_id: uuid.UUID
    ) -> SubmissionResultRead: ...
    async def get_module_summary_for_student(
        self, student_id: uuid.UUID, module_id: uuid.UUID,
    ) -> StudentModuleSummaryRead: ...
    async def get_module_summary_as_professor(
        self, professor_id: uuid.UUID, student_id: uuid.UUID, module_id: uuid.UUID,
    ) -> StudentModuleSummaryRead: ...
    async def list_by_exercise_for_professor(
        self,
        exercise_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> CursorPage[SubmissionSummaryRead]: ...


class EvaluationService:
    def __init__(
        self,
        evaluation_repo: EvaluationRepositoryProtocol,
        submission_repo: SubmissionRepositoryProtocol,
        exercise_repo: ExerciseRepositoryProtocol,
        user_repo: UserRepositoryProtocol,
        extraction_correction_repo: ExtractionCorrectionRepositoryProtocol | None = None,
        reasoning_clarification_repo: ReasoningClarificationRequestRepositoryProtocol | None = None,
        storage_service: StorageService | None = None,
    ) -> None:
        self._evaluation_repo = evaluation_repo
        self._submission_repo = submission_repo
        self._exercise_repo = exercise_repo
        self._user_repo = user_repo
        # Optionnel (2026-09-06) : requis uniquement par get_results_for_
        # student pour distinguer "aucune réponse déposée" de "en attente de
        # correction" (cf. son docstring) — None accepté pour ne pas casser
        # les autres appelants existants de ce service, jamais construits
        # avec ce repo.
        self._extractions = extraction_correction_repo
        # Optionnel (2026-09-06) : requis uniquement par get_results_for_
        # student pour lire LA vraie justification de Comparative_Evaluation_
        # Agent sur une question bloquée (submission_id désormais porté par
        # ReasoningClarificationRequest, cf. son docstring) — même principe
        # que self._extractions ci-dessus.
        self._clarifications = reasoning_clarification_repo
        self._storage = storage_service or StorageService()

    async def record_evaluation(
        self,
        submission_id: uuid.UUID,
        question_id: uuid.UUID,
        score: Decimal,
        classic_criteria_observed: list[dict] | dict,
        criteria_data: list[dict],
        copy_report_detail: dict | None = None,
    ) -> EvaluationRead:
        """
        Persisteur générique — ne connaît plus aucune compétence C2PCT
        (cf. docstring module, point 8) : la mise à jour de
        StudentCompetencyProfile est désormais entièrement hors de ce
        service, portée par CompetencyAssessmentService.
        """
        # 1. Vérification de la soumission
        submission = await self._submission_repo.get_by_id(submission_id)
        if not submission:
            raise SubmissionNotFoundError(submission_id)

        # Phase 4/4 — TODO résolu : une soumission avec au moins une
        # contestation encore en attente de décision professeur ne peut
        # jamais être évaluée (§2 étape 6, doc Contestation_Verification_
        # Agent : "un agent d'évaluation ne peut pas travailler sur une
        # copie encore incertaine"). Vérifié AVANT toute écriture.
        if submission.status == SubmissionStatus.PENDING_ARBITRATION:
            raise SubmissionPendingArbitrationError(submission_id)

        # 2. Création de l'évaluation en base
        evaluation = await self._evaluation_repo.create_with_criteria(
            submission_id=submission_id,
            question_id=question_id,
            score=score,
            classic_criteria_observed=classic_criteria_observed if isinstance(classic_criteria_observed, list) else [classic_criteria_observed],
            criteria_data=criteria_data,
            copy_report_detail=copy_report_detail,
        )

        # 3. Récupération de l'exercice (Submission -> Exercise -> module_id & questions)
        exercise = await self._exercise_repo.get_by_id(submission.exercise_id)
        question_order = 1
        if exercise:
            for q in exercise.questions:
                if q.id == question_id:
                    question_order = q.order
                    break
        evaluation.question_order = question_order

        if not hasattr(evaluation, "criteria") or evaluation.criteria is None:
            evaluation.criteria = []

        return _to_evaluation_read(evaluation, question_order)

    async def record_question_score(
        self,
        submission_id: uuid.UUID,
        bareme_id: uuid.UUID | None,
        result: QuestionScoreResult | ClassicQuestionScoreResult,
        question_report: QuestionReport | None = None,
    ) -> EvaluationRead:
        """
        Phase 4/4 — point d'intégration avec PedagogicalEvaluationAgent.
        evaluate_question() : `result` est DÉJÀ CALCULÉ (aucune logique de
        calcul ici, ce service persiste ce que l'agent a déterminé, jamais
        plus, jamais moins — même principe que tous les services précédents
        de ce projet). Une ligne EvaluationCriteria PAR COMPÉTENCE
        (jamais par sous-question), competency_code + subquestion_detail
        JSONB pour la traçabilité fine sans multiplier les lignes.

        Calcul de note classique (ticket dédié) — `result` accepte désormais
        AUSSI un ClassicQuestionScoreResult (evaluate_question_classic()) :
        une ligne EvaluationCriteria PAR CRITÈRE (criterion_id renseigné,
        competency_code=None — famille "classique" déjà supportée par
        EvaluationCriteria/create_with_criteria, cf. leurs docstrings,
        jamais alimentée par le chemin actif jusqu'ici). Seule la
        construction de criteria_data diffère selon le type de `result` ;
        la persistance elle-même (record_evaluation ci-dessous) reste
        UNIQUE, jamais dupliquée entre les deux mécanismes.

        `bareme_id` : posé tel quel sur EvaluationCriteria.bareme_id (FK
        nullable, 2026-09-06) — None pour une question C2PCT-native (pas de
        ligne Bareme, cf. son docstring). L'agent lui-même ne connaît que
        bareme_points (Decimal), jamais un id (souci de calcul pur, découplé
        de la persistance).

        classic_criteria_observed transmis vide : cet agent ne le produit
        pas (dépassé, cf. docstring module).

        `question_report` : câblage copy_report — QuestionReport déjà
        assemblé par PedagogicalEvaluationAgent.build_question_report()/
        build_question_report_classic(), persisté tel quel
        (QuestionReport.to_dict()) dans Evaluation.copy_report_detail. None
        si non fourni (appelants antérieurs à ce câblage) — jamais construit
        ici, ce service persiste.

        Ne met plus à jour StudentCompetencyProfile (cf. docstring module,
        point 8) — CompetencyAssessmentService.assess_submission (Niveau 2/3,
        Competency_Assessment_Agent) en est désormais l'unique responsable,
        appelé séparément une fois la soumission entièrement notée. Le
        mécanisme classique n'a jamais alimenté ce profil (aucune compétence
        C2PCT associée à un critère de barème classique) — inchangé ici.
        """
        if isinstance(result, ClassicQuestionScoreResult):
            criteria_data = [
                {
                    "bareme_id": bareme_id,
                    "criterion_id": c.criterion_id,
                    "points_awarded": c.points_awarded,
                    "comment": c.justification,
                }
                for c in result.criterion_scores
            ]
        else:
            criteria_data = [
                {
                    "bareme_id": bareme_id,
                    "competency_code": c.competency_code,
                    "points_awarded": c.points_awarded,
                    "subquestion_detail": {
                        "subquestions": [
                            {
                                "subquestion_id": d.subquestion_id,
                                "addressed": d.addressed,
                                "is_correct": d.is_correct,
                                "source": d.source,
                                # Chantier notation graduée (Partie 2/3) — taux
                                # fin par sous-question, None si addressed=False
                                # ou jugement manquant (même sémantique que
                                # SubquestionScoreDetail.completion_ratio).
                                "completion_ratio": float(d.completion_ratio) if d.completion_ratio is not None else None,
                            }
                            for d in c.subquestion_detail
                        ],
                        "covered_count": c.covered_count,
                        "successful_count": c.successful_count,
                        "success_rate": float(c.success_rate),
                    },
                }
                for c in result.competency_scores
            ]

        return await self.record_evaluation(
            submission_id=submission_id,
            question_id=result.question_id,
            score=result.total_score,
            classic_criteria_observed=[],
            criteria_data=criteria_data,
            copy_report_detail=question_report.to_dict() if question_report is not None else None,
        )

    async def get_total_score(self, submission_id: uuid.UUID) -> Decimal:
        return await self._evaluation_repo.get_total_score_for_submission(submission_id)

    async def get_copy_report(self, submission_id: uuid.UUID) -> CopyReport:
        """
        Câblage copy_report (§0) — agrégation à la LECTURE des QuestionReport
        déjà persistés (Evaluation.copy_report_detail), une par question,
        même principe que get_total_score_for_submission (agrégat calculé,
        jamais un document dupliqué stocké séparément au niveau soumission,
        cf. docstring evaluation.py). Une question sans copy_report_detail
        (ligne écrite avant ce câblage, ou question blocking jamais notée,
        cf. evaluation_node.py) est simplement ABSENTE du CopyReport — jamais
        un QuestionReport deviné pour la compléter artificiellement.
        """
        evaluations = await self._evaluation_repo.list_by_submission(submission_id)
        questions: list[QuestionReport] = []
        for evaluation in evaluations:
            if evaluation.copy_report_detail is None:
                continue
            questions.append(QuestionReport.from_dict(evaluation.copy_report_detail))

        questions_sans_ambiguite = sum(
            1 for q in questions
            if not any(
                d.decision in ("NOT_ADDRESSED", "INCORRECT")
                for line in q.competency_lines
                for d in line.decisions
            )
        )
        questions_necessitant_un_regard = len(questions) - questions_sans_ambiguite
        consigne_non_respectee_count = sum(1 for q in questions if q.consigne_respected is False)

        overview = {
            "questions_sans_ambiguite": questions_sans_ambiguite,
            "questions_necessitant_un_regard": questions_necessitant_un_regard,
            "consigne_non_respectee_count": consigne_non_respectee_count,
        }

        return CopyReport(submission_id=submission_id, overview=overview, questions=questions)

    async def list_evaluations(self, submission_id: uuid.UUID) -> list[EvaluationRead]:
        submission = await self._submission_repo.get_by_id(submission_id)
        if not submission:
            raise SubmissionNotFoundError(submission_id)

        exercise = await self._exercise_repo.get_by_id(submission.exercise_id)
        evaluations = await self._evaluation_repo.list_by_submission(submission_id)
        questions_by_id = {q.id: q.order for q in exercise.questions} if exercise else {}

        await self._attach_criteria(evaluations, exercise)

        result: list[EvaluationRead] = []
        for evaluation in evaluations:
            q_order = questions_by_id.get(evaluation.question_id, 1)
            result.append(_to_evaluation_read(evaluation, q_order))
        return result

    async def _attach_criteria(
        self, evaluations: list[Evaluation], exercise: Exercise | None
    ) -> None:
        """
        Gap fermé (espace étudiant, trouvé en testant un vrai relevé de
        notes de bout en bout) : Evaluation n'a AUCUNE relation ORM
        "criteria" déclarée (vérifié, cf. docstring module evaluation_
        repository.py — "jointure directe" requise). Sans peuplement
        transitoire explicite ici, EvaluationRead.criteria (champ requis,
        non optionnel) échoue TOUJOURS à la validation Pydantic dès qu'une
        Evaluation relue depuis la DB passe par _to_evaluation_read — que
        ce soit get_evaluation() ou list_evaluations(). Jamais détecté
        avant : tous les tests unitaires mockent evaluation_repo, aucun ne
        relit une vraie Evaluation persistée. Résout aussi criterion_label
        depuis Bareme.criteria (JSON) de la question correspondante — la
        vraie donnée, jamais l'id brut comme fallback (contrairement au
        comportement précédent de _to_evaluation_read, conservé mais
        rendu inatteignable puisque criterion_label est déjà résolu ici).
        """
        evaluation_ids = [e.id for e in evaluations]
        all_criteria = await self._evaluation_repo.list_criteria_by_evaluation_ids(evaluation_ids)

        by_evaluation: dict[uuid.UUID, list] = {}
        for c in all_criteria:
            by_evaluation.setdefault(c.evaluation_id, []).append(c)

        labels_by_question: dict[uuid.UUID, dict[str, str]] = {}
        if exercise:
            for q in exercise.questions:
                if q.bareme:
                    labels_by_question[q.id] = {crit["id"]: crit["label"] for crit in q.bareme.criteria}

        for evaluation in evaluations:
            criteria = by_evaluation.get(evaluation.id, [])
            labels = labels_by_question.get(evaluation.question_id, {})
            for c in criteria:
                c.criterion_label = labels.get(c.criterion_id) if c.criterion_id is not None else None
            evaluation.criteria = criteria

    async def _authorize_submission_access(
        self, submission: Submission, requesting_user: User
    ) -> None:
        """
        Faille corrigée (audit résultats professeur) : GET /evaluations/{id}
        et GET /submissions/{id}/evaluations n'avaient AUCUN contrôle
        d'accès au-delà d'être authentifié — n'importe quel étudiant pouvait
        consulter l'évaluation détaillée de N'IMPORTE QUELLE soumission en
        devinant son id, pas seulement la sienne. Même politique que
        get_student_competency_profile (results_router.py) : étudiant
        propriétaire de la soumission, ou professeur créateur de l'exercice
        — jamais un admin ici (aucun outil d'audit académique ne l'exige,
        cf. décision équivalente pour compétences/recommandations).
        """
        requesting_user_id = uuid.UUID(str(requesting_user.id))

        if requesting_user.role == UserRole.STUDENT:
            if requesting_user_id != submission.student_id:
                raise ForbiddenError("Un étudiant ne peut consulter que ses propres évaluations.")
            return

        if requesting_user.role == UserRole.PROFESSOR:
            exercise = await self._exercise_repo.get_by_id(submission.exercise_id)
            if exercise is None or exercise.created_by_professor_id != requesting_user_id:
                raise ForbiddenError(
                    "Seul le professeur créateur de l'exercice peut consulter ces évaluations."
                )
            return

        raise ForbiddenError(
            "Accès aux évaluations réservé à l'étudiant concerné ou à son professeur."
        )

    async def get_evaluation(self, evaluation_id: uuid.UUID, requesting_user: User) -> EvaluationRead:
        evaluation = await self._evaluation_repo.get_by_id(evaluation_id)
        if evaluation is None:
            raise EvaluationNotFoundError(evaluation_id)

        submission = await self._submission_repo.get_by_id(evaluation.submission_id)
        if submission is None:
            raise SubmissionNotFoundError(evaluation.submission_id)

        await self._authorize_submission_access(submission, requesting_user)

        exercise = await self._exercise_repo.get_by_id(submission.exercise_id)
        question_order = 1
        if exercise:
            for q in exercise.questions:
                if q.id == evaluation.question_id:
                    question_order = q.order
                    break

        await self._attach_criteria([evaluation], exercise)

        return _to_evaluation_read(evaluation, question_order)

    async def list_evaluations_for_submission(
        self, submission_id: uuid.UUID, requesting_user: User
    ) -> list[EvaluationRead]:
        submission = await self._submission_repo.get_by_id(submission_id)
        if submission is None:
            raise SubmissionNotFoundError(submission_id)

        await self._authorize_submission_access(submission, requesting_user)

        return await self.list_evaluations(submission_id)

    async def get_copy_report_for_professor(
        self, submission_id: uuid.UUID, requesting_professor_id: uuid.UUID
    ) -> CopyReport:
        """
        Gap trouvé lors de l'audit résultats professeur : get_copy_report
        existait déjà (agrégat "questions ambiguës / à revoir / consigne non
        respectée") mais n'était exposé par AUCUN endpoint. Réservé au
        professeur créateur de l'exercice — jamais l'étudiant (ce rapport
        est un outil de correction, pas un livrable pédagogique comme
        get_evaluation/list_evaluations_for_submission ci-dessus).
        """
        submission = await self._submission_repo.get_by_id(submission_id)
        if submission is None:
            raise SubmissionNotFoundError(submission_id)

        exercise = await self._exercise_repo.get_by_id(submission.exercise_id)
        if exercise is None or exercise.created_by_professor_id != requesting_professor_id:
            raise NotExerciseOwnerError(submission.exercise_id, requesting_professor_id)

        return await self.get_copy_report(submission_id)

    async def get_results_for_student(
        self, submission_id: uuid.UUID, requesting_student_id: uuid.UUID
    ) -> SubmissionResultRead:
        """
        Écran dédié "Mes résultats" (gap fermé, test réel 2026-08-31) —
        distinct de get_copy_report_for_professor : ici seulement score/
        barème par question + total, jamais les justifications techniques
        d'un outil de correction. Self-only (pas le contrôle bi-rôle de
        _authorize_submission_access — un professeur a déjà copy-report,
        pensé pour lui).
        """
        submission = await self._submission_repo.get_by_id(submission_id)
        if submission is None:
            raise SubmissionNotFoundError(submission_id)
        if submission.student_id != requesting_student_id:
            raise ForbiddenError("Un étudiant ne peut consulter que ses propres résultats.")

        exercise = await self._exercise_repo.get_by_id(submission.exercise_id)
        # Bug réel corrigé (2026-09-06, test réel — "Mes résultats" affichait
        # 0/0 pour un examen entièrement C2PCT-natif) : filtrer sur
        # `q.bareme is not None` excluait TOUTE question sans Bareme
        # classique — exactement le même trou que celui déjà corrigé dans
        # comparative_evaluation_node.py (cf. son correctif "subquestion_
        # points") mais jamais reporté ici. Toutes les questions de
        # l'exercice sont désormais incluses, classique ou C2PCT-native.
        all_questions = sorted(
            (exercise.questions if exercise else []), key=lambda q: q.order,
        )

        evaluations = await self._evaluation_repo.list_by_submission(submission_id)
        score_by_question = {e.question_id: e.score for e in evaluations}

        # Bug réel corrigé (2026-09-06, test réel — cas salma, copie hors-
        # sujet) : une question non notée affichait un badge générique "Pas
        # encore corrigée" sans jamais dire POURQUOI — un professeur/étudiant
        # ne pouvait pas distinguer "aucune réponse déposée pour cette
        # question précise" (rien à juger, cf. comparative_evaluation_node.py
        # ligne `if not student_answer_text: continue`) d'un vrai retard de
        # correction. questions_with_content dérivé des ExtractionCorrection
        # réellement rattachées (question_id non NULL), même source que ce
        # que comparative_evaluation_node.py lit lui-même. self._extractions
        # optionnel (cf. constructeur) : repli silencieux sur l'ancien
        # comportement générique si jamais appelé sans ce repo.
        questions_with_content: set[uuid.UUID] = set()
        if self._extractions is not None:
            corrections = await self._extractions.get_by_submission_id(submission_id)
            questions_with_content = {
                c.question_id for c in corrections if c.question_id is not None
            }

        # Bug corrigé (2026-09-02, cas réel zainabsebhi) : TOUTES les
        # questions du barème apparaissent désormais ici, y compris celles
        # sans Evaluation — l'ancien comportement (une ligne par Evaluation
        # seulement) faisait disparaître silencieusement une question jamais
        # rattachée/notée, gonflant du même coup le score en pourcentage
        # affiché puisque le dénominateur rétrécissait avec elle. is_graded
        # rend l'absence explicite plutôt que de la masquer.
        questions: list[QuestionResultRead] = []
        for q in all_questions:
            is_graded = q.id in score_by_question
            not_graded_reason: str | None = None
            blocking_justification: str | None = None
            if not is_graded and self._extractions is not None:
                if q.id not in questions_with_content:
                    not_graded_reason = "no_student_answer"
                else:
                    not_graded_reason = "pending_review"
                    # Bug réel corrigé (2026-09-06, cas réel — label
                    # générique "en cours de correction" sans jamais dire
                    # pourquoi) : LA justification réelle de Comparative_
                    # Evaluation_Agent, désormais rattachable sans ambiguïté
                    # à CETTE soumission précise (submission_id, cf. son
                    # correctif). None si aucune clarification BLOCKING
                    # trouvée (ex. échec technique silencieux plutôt qu'un
                    # blocage réellement posé par l'agent) — le label
                    # générique reste alors le seul repli honnête.
                    if self._clarifications is not None:
                        pending = await self._clarifications.list_pending_blocking_by_question_and_submission(
                            question_id=q.id, submission_id=submission_id,
                        )
                        if pending:
                            blocking_justification = pending[0].agent_question
            questions.append(
                QuestionResultRead(
                    question_id=q.id,
                    question_order=q.order,
                    score=score_by_question.get(q.id),
                    max_score=q.max_points,
                    is_graded=is_graded,
                    not_graded_reason=not_graded_reason,
                    blocking_justification=blocking_justification,
                )
            )

        return SubmissionResultRead(
            submission_id=submission_id,
            exercise_title=exercise.title if exercise else "Unknown",
            total_score=sum((q.score for q in questions if q.score is not None), Decimal("0")),
            max_score=sum((q.max_score for q in questions), Decimal("0")),
            is_fully_graded=all(q.is_graded for q in questions),
            questions=questions,
        )

    async def _score_and_max_for_submission(self, submission: Submission) -> tuple[Decimal, Decimal]:
        """
        (total_score, max_score) d'UNE soumission déjà évaluée. Bug corrigé
        (2026-09-02) : max_score est désormais le VRAI total du barème de
        l'exercice (toutes les questions, notées ou non), même règle que
        get_results_for_student — l'ancien calcul (dénominateur restreint
        aux seules questions ayant déjà une Evaluation) sous-évaluait
        silencieusement le total d'un exercice partiellement corrigé.
        Factorisé ici pour être réutilisé par get_module_summary_for_student
        sans dupliquer la logique.
        """
        exercise = await self._exercise_repo.get_by_id(submission.exercise_id)
        max_score = sum(
            (q.max_points for q in (exercise.questions if exercise else [])),
            Decimal("0"),
        )
        evaluations = await self._evaluation_repo.list_by_submission(submission.id)
        total_score = sum((e.score for e in evaluations), Decimal("0"))
        return total_score, max_score

    async def get_module_summary_for_student(
        self, student_id: uuid.UUID, module_id: uuid.UUID,
    ) -> StudentModuleSummaryRead:
        """
        Écran "Profil de compétence" (bloc infos étudiant) — total de copies
        déposées/notées et note moyenne pour CE module. La garde d'accès
        professeur (module-scoped) vit dans get_module_summary_as_professor
        ci-dessous, jamais ici (même séparation self/professeur que get_
        report / get_report_as_professor de CompetencyAssessmentService).
        """
        exercise_ids = await self._exercise_repo.list_ids_by_module(module_id)
        total_submissions = await self._submission_repo.count_by_student_and_exercise_ids(
            student_id, exercise_ids,
        )
        evaluated = await self._submission_repo.list_evaluated_by_student_and_exercise_ids(
            student_id, exercise_ids,
        )

        total_score = Decimal("0")
        max_score = Decimal("0")
        for submission in evaluated:
            s_score, s_max = await self._score_and_max_for_submission(submission)
            total_score += s_score
            max_score += s_max

        return StudentModuleSummaryRead(
            student_id=student_id,
            module_id=module_id,
            total_submissions=total_submissions,
            evaluated_submissions=len(evaluated),
            total_score=total_score,
            max_score=max_score,
        )

    async def get_module_summary_as_professor(
        self, professor_id: uuid.UUID, student_id: uuid.UUID, module_id: uuid.UUID,
    ) -> StudentModuleSummaryRead:
        """Même garde d'accès que CompetencyAssessmentService.get_report_as_professor — jamais réécrite à la main."""
        has_exercise_in_module = await self._exercise_repo.exists_professor_exercise_in_module(
            professor_id, module_id,
        )
        if not has_exercise_in_module:
            raise ForbiddenError(
                f"Le professeur {professor_id} n'a aucun exercice dans le module {module_id}."
            )
        return await self.get_module_summary_for_student(student_id, module_id)

    async def list_by_exercise_for_professor(
        self,
        exercise_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> CursorPage[SubmissionSummaryRead]:
        """
        Gap trouvé lors de l'audit résultats professeur : SubmissionRepository.
        list_by_exercise existait déjà (utilisé en interne par ExerciseService.
        delete pour bloquer la suppression d'un exercice avec copies) mais
        n'était exposé par AUCUN endpoint — un professeur n'avait aucun moyen
        de voir les copies déposées sur un de ses exercices sans déjà
        connaître un submission_id (uniquement via contestations/arbitrage,
        qui ne couvrent que les cas litigieux).
        """
        exercise = await self._exercise_repo.get_by_id(exercise_id)
        if exercise is None:
            raise ExerciseNotFoundError(exercise_id)

        if exercise.created_by_professor_id != requesting_professor_id:
            raise NotExerciseOwnerError(exercise_id, requesting_professor_id)

        page = await self._submission_repo.list_by_exercise(exercise_id, cursor=cursor, limit=limit)

        # Barème max par question calculé UNE SEULE FOIS pour tout le
        # module (toutes les soumissions de cette page partagent le même
        # exercise_id) — jamais un re-fetch de l'exercice par soumission,
        # contrairement à _score_and_max_for_submission (pensée pour un
        # appel isolé, pas une boucle de liste).
        max_score_by_question = {q.id: q.max_points for q in exercise.questions}

        items: list[SubmissionSummaryRead] = []
        for submission in page.items:
            student = await self._user_repo.get_by_id(submission.student_id)
            if submission.status == SubmissionStatus.EVALUATED:
                evaluations = await self._evaluation_repo.list_by_submission(submission.id)
                total_score = sum((e.score for e in evaluations), Decimal("0"))
                max_score = sum(
                    (max_score_by_question.get(e.question_id, Decimal("0")) for e in evaluations), Decimal("0"),
                )
            else:
                total_score = None
                max_score = None
            document_url = (
                self._storage.generate_read_url(StorageContainer.SUBMISSIONS, submission.document_path)
                if submission.document_path
                else None
            )
            items.append(
                SubmissionSummaryRead(
                    id=submission.id,
                    student_id=submission.student_id,
                    student_full_name=f"{student.first_name} {student.last_name}" if student else "Unknown",
                    attempt_number=submission.attempt_number,
                    status=submission.status,
                    total_score=total_score,
                    max_score=max_score,
                    created_at=submission.created_at,
                    document_url=document_url,
                )
            )

        return CursorPage(items=items, next_cursor=page.next_cursor, has_more=page.has_more)

