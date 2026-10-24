

"""
Hiérarchie d'exceptions métier du projet.

Toutes les exceptions levées par les services et repositories doivent
hériter de ces classes de base pour permettre un traitement uniforme
au niveau des routers FastAPI (gestion des codes HTTP, logging, etc.).

Hiérarchie :
    DomainError (base)
    ├── NotFoundError : entité introuvable (404)
    ├── ConflictError : conflit métier, duplication (409)
    ├── ForbiddenError : accès refusé, droits insuffisants (403)
    ├── ValidationError : données invalides (422)
    └── ExternalServiceError : service tiers non garanti indisponible (503)
"""
import uuid
from decimal import Decimal


class DomainError(Exception):
    """Base de toutes les exceptions métier."""
    pass


class NotFoundError(DomainError):
    """Entité introuvable en base de données."""
    pass


class ConflictError(DomainError):
    """Conflit métier : duplication, contrainte violée."""
    pass


class ForbiddenError(DomainError):
    """Accès refusé : droits insuffisants ou statut interdisant l'action."""
    pass


class ExternalServiceError(DomainError):
    """
    Service tiers non garanti indisponible (503) — câblage NotebookLM,
    §7 Partie 2/2 : jamais utilisée pour un échec best-effort (ceux-là ne
    lèvent JAMAIS, cf. NotebookLMService), uniquement pour un chemin
    SYNCHRONE où l'étudiant attend activement une réponse en direct
    (notebook-chat) — pas de fallback possible, une vraie erreur HTTP est
    la réponse honnête, pas un succès silencieux avec une réponse vide.
    """
    pass


class ValidationError(DomainError):
    """Données invalides : format incorrect, valeur hors bornes, etc."""
    pass


# --- Agent & OCR Domain Errors ---

class DocumentQualityError(ValidationError):
    """Qualité visuelle de la copie/document insuffisante (flou, obscur, inclinance)."""
    def __init__(self, reason: str, details: dict | None = None) -> None:
        self.details = details or {}
        super().__init__(f"Qualité du document insuffisante : {reason}")


class LLMBudgetExceededError(DomainError):
    """
    Plafond d'appels LLM dépassé pour un thread (audit "garanties
    transverses", Plan D) — échec propre plutôt qu'une boucle de retries/
    fallbacks qui continuerait silencieusement. Levée par
    invoke_llm_with_fallback AVANT toute tentative, jamais après coup.
    """
    def __init__(self, thread_id: str, max_calls: int) -> None:
        self.thread_id = thread_id
        self.max_calls = max_calls
        super().__init__(
            f"Plafond d'appels LLM ({max_calls}) dépassé pour le thread {thread_id}"
        )


class VisionProviderError(DomainError):
    """Échec de l'ensemble des fournisseurs Vision LLM (primaire et fallbacks)."""
    def __init__(self, message: str, errors: list[Exception] | None = None) -> None:
        self.errors = errors or []
        super().__init__(f"Erreur des fournisseurs Vision : {message}")


class OCRExtractionError(DomainError):
    """Échec de la structuration ou de l'extraction OCR des blocs."""
    def __init__(self, message: str) -> None:
        super().__init__(f"Erreur d'extraction OCR : {message}")


class LatexValidationError(ValidationError):
    """Échec de validation de la syntaxe LaTeX d'une équation."""
    def __init__(self, latex_str: str, reason: str) -> None:
        self.latex_str = latex_str
        super().__init__(f"Syntaxe LaTeX invalide ('{latex_str}') : {reason}")


# --- NotFoundError ---

class ExerciseNotFoundError(NotFoundError):
    """Exercice introuvable en base de données."""
    def __init__(self, exercise_id: uuid.UUID) -> None:
        super().__init__(f"Exercice introuvable (ID: {exercise_id})")


class ModuleNotFoundError(NotFoundError):
    """Module (entité académique) introuvable en base de données."""
    def __init__(self, module_id: uuid.UUID) -> None:
        super().__init__(f"Module introuvable (ID: {module_id})")


class QuestionNotFoundError(NotFoundError):
    """Question introuvable en base de données."""
    def __init__(self, question_id: uuid.UUID) -> None:
        super().__init__(f"Question introuvable (ID: {question_id})")


class StudentNotFoundError(NotFoundError):
    """Étudiant introuvable en base de données."""
    def __init__(self, student_id: uuid.UUID) -> None:
        super().__init__(f"Étudiant introuvable (ID: {student_id})")


class SubmissionNotFoundError(NotFoundError):
    """Soumission introuvable en base de données."""
    def __init__(self, submission_id: uuid.UUID) -> None:
        super().__init__(f"Soumission introuvable (ID: {submission_id})")


class JobNotFoundError(NotFoundError):
    """Job introuvable en base de données (supervision admin)."""
    def __init__(self, job_id: uuid.UUID) -> None:
        super().__init__(f"Job introuvable (ID: {job_id})")


class StudentSuspendedError(ForbiddenError):
    """Étudiant suspendu, action refusée."""
    def __init__(self, student_id: uuid.UUID) -> None:
        super().__init__(f"Étudiant suspendu, soumission refusée (ID: {student_id})")


# --- Autres NotFoundError ---

class IncidentNotFoundError(NotFoundError):
    """Incident introuvable."""
    def __init__(self, incident_id: uuid.UUID) -> None:
        super().__init__(f"Incident introuvable (ID: {incident_id})")


class CourseNotFoundError(NotFoundError):
    """Cours introuvable."""
    def __init__(self, course_id: uuid.UUID) -> None:
        super().__init__(f"Cours introuvable (ID: {course_id})")


class RequestNotFoundError(NotFoundError):
    """Demande introuvable."""
    def __init__(self, request_id: uuid.UUID) -> None:
        super().__init__(f"Demande introuvable (ID: {request_id})")


class EvaluationNotFoundError(NotFoundError):
    """Évaluation introuvable."""
    def __init__(self, evaluation_id: uuid.UUID) -> None:
        super().__init__(f"Évaluation introuvable (ID: {evaluation_id})")


class FeedbackNotFoundError(NotFoundError):
    """Feedback introuvable."""
    def __init__(self, feedback_id: uuid.UUID) -> None:
        super().__init__(f"Feedback introuvable (ID: {feedback_id})")


class AppealNotFoundError(NotFoundError):
    """Contestation introuvable."""
    def __init__(self, appeal_id: uuid.UUID) -> None:
        super().__init__(f"Contestation introuvable (ID: {appeal_id})")


class GroupNotFoundError(NotFoundError):
    """Groupe introuvable."""
    def __init__(self, group_id: uuid.UUID) -> None:
        super().__init__(f"Groupe introuvable (ID: {group_id})")


class AlertNotFoundError(NotFoundError):
    """Alerte introuvable."""
    def __init__(self, alert_id: uuid.UUID) -> None:
        super().__init__(f"Alerte introuvable (ID: {alert_id})")


class ProgramNotFoundError(NotFoundError):
    """Programme introuvable."""
    def __init__(self, program_id: uuid.UUID) -> None:
        super().__init__(f"Programme introuvable (ID: {program_id})")


class NotificationNotFoundError(NotFoundError):
    """Notification introuvable."""
    def __init__(self, notification_id: uuid.UUID) -> None:
        super().__init__(f"Notification introuvable (ID: {notification_id})")


class VariantNotFoundError(NotFoundError):
    """Variante de solution introuvable."""
    def __init__(self, variant_id: uuid.UUID) -> None:
        super().__init__(f"Variante de solution introuvable (ID: {variant_id})")


class ClarificationRequestNotFoundError(NotFoundError):
    """Demande de clarification introuvable."""
    def __init__(self, request_id: uuid.UUID) -> None:
        super().__init__(f"Demande de clarification introuvable (ID: {request_id})")


class ReasoningStepNotFoundError(NotFoundError):
    """Étape de raisonnement introuvable (correction ciblée par le professeur)."""
    def __init__(self, step_id: uuid.UUID) -> None:
        super().__init__(f"Étape de raisonnement introuvable (ID: {step_id})")


class InvalidClarificationTypeError(ValidationError):
    """
    Câblage HITL indexation RAG (Priorité 1) — la demande de clarification
    ciblée n'est pas une clarification MULTIPLE_DISTINCT_ANSWERS de
    Comparative_Evaluation_Agent (criterion_id absent) : validate-alternative-
    answer ne s'applique jamais à une clarification Reasoning_Graph_Agent/
    Extraction_Verification_Agent (jamais un accept/reject deviné pour un
    type de clarification qui n'en a pas la sémantique).
    """
    def __init__(self, request_id: uuid.UUID) -> None:
        super().__init__(
            f"Demande de clarification {request_id} n'est pas une clarification de "
            f"réponse alternative (MULTIPLE_DISTINCT_ANSWERS) — validation impossible."
        )


class EnrollmentNotFoundError(NotFoundError):
    """Inscription introuvable."""
    def __init__(self, enrollment_id: uuid.UUID) -> None:
        super().__init__(f"Inscription introuvable (ID: {enrollment_id})")


# --- ConflictError ---

class DuplicateIncidentError(ConflictError):
    """Incident en doublon."""
    def __init__(self, student_id: uuid.UUID, exercise_id: uuid.UUID) -> None:
        super().__init__(
            f"Un incident en attente existe déjà pour l'étudiant {student_id} "
            f"sur l'exercice {exercise_id}"
        )


class CourseHasActiveExercisesError(ConflictError):
    """Cours a des exercices actifs."""
    def __init__(self, course_id: uuid.UUID) -> None:
        super().__init__(f"Le cours {course_id} a des exercices actifs")


class ExerciseHasSubmissionsError(ConflictError):
    """Exercice a des soumissions étudiantes — jamais supprimable, même en DRAFT."""
    def __init__(self, exercise_id: uuid.UUID) -> None:
        super().__init__(f"L'exercice {exercise_id} a des soumissions et ne peut pas être supprimé")


class ExerciseNotDraftError(ConflictError):
    """Seul un exercice DRAFT peut être supprimé (publié/archivé : jamais)."""
    def __init__(self, exercise_id: uuid.UUID, status: str) -> None:
        super().__init__(
            f"L'exercice {exercise_id} ne peut être supprimé qu'en statut DRAFT (statut actuel : {status})"
        )


class StructuringNotInterruptedError(ConflictError):
    """
    Confirmation de structuration demandée alors qu'aucun pipeline n'est
    réellement en pause pour cet exercice (Job.status == INTERRUPTED) —
    ex. déjà confirmé, jamais démarré, ou terminé sans interruption.
    """
    def __init__(self, exercise_id: uuid.UUID) -> None:
        super().__init__(
            f"Aucune structuration en attente de confirmation pour l'exercice {exercise_id}"
        )


class MinimumQuestionCountError(ConflictError):
    """Un exercice doit toujours garder au moins une Question (cf. ExerciseCreateRequest.questions, min_length=1)."""
    def __init__(self, exercise_id: uuid.UUID) -> None:
        super().__init__(
            f"L'exercice {exercise_id} doit conserver au moins une question"
        )


class GroupAlreadyExistsError(ConflictError):
    """Groupe déjà existant."""
    def __init__(self, program_id: uuid.UUID, label: str) -> None:
        super().__init__(f"Le groupe {label} existe déjà pour le programme {program_id}")


class GroupHasActiveDependenciesError(ConflictError):
    """Groupe a des dépendances actives."""
    def __init__(self, group_id: uuid.UUID) -> None:
        super().__init__(f"Le groupe {group_id} a des dépendances actives")


class ProgramAlreadyExistsError(ConflictError):
    """Programme déjà existant."""
    def __init__(self, name: str, code: str) -> None:
        super().__init__(f"Le programme {name} ({code}) existe déjà")


class ProgramHasActiveDependenciesError(ConflictError):
    """Programme a des dépendances actives."""
    def __init__(self, program_id: uuid.UUID, module_count: int = 0, group_count: int = 0) -> None:
        detail = f"Le programme {program_id} a des dépendances actives"
        if module_count or group_count:
            detail += f" ({module_count} module(s), {group_count} groupe(s))"
        super().__init__(detail)


class ModuleAlreadyExistsError(ConflictError):
    """Module déjà existant (nom ou code en doublon)."""
    def __init__(self, name: str, code: str) -> None:
        super().__init__(f"Un module existe déjà avec le nom '{name}' ou le code '{code}'")


class ModuleHasActiveDependenciesError(ConflictError):
    """Module a des exercices ou inscriptions actifs."""
    def __init__(self, module_id: uuid.UUID) -> None:
        super().__init__(
            f"Impossible de supprimer le module {module_id} : "
            f"des exercices ou des inscriptions actives en dépendent encore"
        )


class ModuleInvalidProgramError(ValidationError):
    """Le programme parent référencé n'existe pas (violation de FK)."""
    def __init__(self, program_id: uuid.UUID) -> None:
        super().__init__(f"Le programme {program_id} n'existe pas")


class AlreadySubmittedError(ConflictError):
    """Déjà soumis."""
    def __init__(self, exercise_id: uuid.UUID, student_id: uuid.UUID) -> None:
        super().__init__(f"L'étudiant {student_id} a déjà soumis pour l'exercice {exercise_id}")


class DeadlinePassedError(ConflictError):
    """Deadline dépassée."""
    def __init__(self, exercise_id: uuid.UUID) -> None:
        super().__init__(f"La date limite pour l'exercice {exercise_id} est dépassée")


class SubmissionResumeDispatchError(ExternalServiceError):
    """
    Bug réel trouvé en testant confirm_submission de bout en bout (jamais
    exercé avant : aucun appelant n'atteignait ce point avant ce chantier) :
    process_job_resumed.delay()/process_contestation_verification.delay()
    (ExtractionService) ne sont protégés par AUCUN try/except — un broker
    Celery injoignable (kombu.exceptions.OperationalError) faisait planter
    la requête HTTP en 500 brut. Contrairement à l'événement Kafka
    submission-created.v1 (rendu best-effort, cf. SubmissionService.
    create_submission) : ici, l'action ELLE-MÊME est ce dispatch — un
    succès silencieux mentirait à l'étudiant ("copie confirmée") alors que
    rien ne reprendrait jamais le pipeline. Une erreur 503 claire et
    réessayable est la réponse honnête, jamais un succès simulé.
    """
    def __init__(self, submission_id: uuid.UUID) -> None:
        super().__init__(
            f"Impossible de relancer le traitement de la soumission {submission_id} pour le "
            "moment (service de tâches indisponible) — réessayez dans un instant."
        )


class SubmissionNotPendingVerificationError(ConflictError):
    """
    Confirmation étudiante ("je confirme ma copie", cf. job_tasks.py) hors
    de la seule fenêtre où elle a un sens : le thread LangGraph n'est en
    pause à await_student_verification_node QUE pendant PENDING_STUDENT_
    VERIFICATION — un resume("confirmed") à tout autre statut ne
    correspondrait à aucune pause réelle (déjà confirmée, en arbitrage, ou
    pas encore extraite).
    """
    def __init__(self, submission_id: uuid.UUID, current_status: str) -> None:
        super().__init__(
            f"La soumission {submission_id} n'est pas en attente de vérification "
            f"étudiante (statut actuel : {current_status})"
        )


class ExerciseNotPublishedError(ConflictError):
    """Exercice non publié."""
    def __init__(self, exercise_id: uuid.UUID) -> None:
        super().__init__(f"L'exercice {exercise_id} n'est pas publié")


class AlreadyEnrolledError(ConflictError):
    """Déjà inscrit au module."""
    def __init__(self, student_id: uuid.UUID, module_id: uuid.UUID) -> None:
        super().__init__(f"L'étudiant {student_id} est déjà inscrit au module {module_id}")


class SubmissionPendingArbitrationError(ConflictError):
    """
    Pedagogical_Evaluation_Agent (Phase 4/4) : une soumission avec au moins
    une contestation encore en attente de décision professeur (§2 étape 6,
    doc Contestation_Verification_Agent) ne peut pas être évaluée — une
    copie encore incertaine ne doit jamais recevoir de note.
    """
    def __init__(self, submission_id: uuid.UUID) -> None:
        super().__init__(
            f"Soumission {submission_id} en attente d'arbitrage (PENDING_ARBITRATION) — "
            "évaluation refusée tant qu'une contestation n'est pas résolue par le professeur."
        )


# --- ForbiddenError ---

class NotExerciseOwnerError(ForbiddenError):
    """Pas le propriétaire de l'exercice."""
    def __init__(self, exercise_id: uuid.UUID, professor_id: uuid.UUID) -> None:
        super().__init__(
            f"Le professeur {professor_id} n'est pas le créateur de "
            f"l'exercice {exercise_id} et ne peut pas le publier"
        )


class NotCourseOwnerError(ForbiddenError):
    """Pas le titulaire du cours (professor_user_id)."""
    def __init__(self, course_id: uuid.UUID, professor_id: uuid.UUID) -> None:
        super().__init__(
            f"Le professeur {professor_id} n'est pas le titulaire du cours {course_id}"
        )


class NotEnrolledError(ForbiddenError):
    """Non inscrit au module."""
    def __init__(self, student_id: uuid.UUID, module_id: uuid.UUID) -> None:
        super().__init__(f"Étudiant {student_id} non inscrit au module {module_id}")


class NotInExamGroupError(ForbiddenError):
    """Pas dans le groupe du cours."""
    def __init__(self, student_id: uuid.UUID, course_id: uuid.UUID) -> None:
        super().__init__(f"Étudiant {student_id} non assigné au groupe du cours {course_id}")


# --- ValidationError ---

class CourseInvalidReferenceError(ValidationError):
    """Référence invalide dans le cours."""
    def __init__(self, field: str, value: uuid.UUID) -> None:
        super().__init__(f"Référence invalide : {field}={value}")


class CourseAlreadyExistsError(ConflictError):
    """Un cours (module, groupe, semestre) existe déjà — contrainte unique."""
    def __init__(self, module_id: uuid.UUID, group_id: uuid.UUID, semester: str) -> None:
        super().__init__(
            f"Un cours existe déjà pour ce module, ce groupe et le semestre {semester}"
        )


class InvalidAcademicYearFormatError(ValidationError):
    """Format d'année académique invalide."""
    def __init__(self, academic_year: str) -> None:
        super().__init__(f"Format d'année académique invalide : {academic_year}")


class InvalidRelevanceScoreError(ValidationError):
    """Score de pertinence invalide."""
    def __init__(self, score: Decimal) -> None:
        super().__init__(f"Score de pertinence invalide : {score}")


class PublicationNotConfirmedError(ValidationError):
    """
    L'exercice ne peut pas être publié : confirmation professeur manquante
    ou périmée. Levée par exercise_service.publish() après la vérification
    de complétude (IncompleteExerciseSetupError), jamais à sa place —
    les deux verrous sont indépendants et cumulatifs.

    stale=True : une confirmation existe (publication_confirmed_hash posé)
    mais l'état réel (barème/variante de référence) a changé depuis —
    distinct de "jamais confirmée du tout" (stale=False), pour un message
    d'erreur qui oriente correctement le professeur.
    """
    def __init__(self, exercise_id: uuid.UUID, stale: bool) -> None:
        self.stale = stale
        reason = (
            "la confirmation existante ne correspond plus à l'état actuel "
            "(barème ou variante de référence modifié depuis) — reconfirmez "
            "via /confirm-publication-readiness"
            if stale
            else "aucune confirmation de publication n'a été posée — "
            "appelez /confirm-publication-readiness avant de publier"
        )
        super().__init__(
            f"L'exercice {exercise_id} ne peut pas être publié : {reason}"
        )


class MissingDifficultyLevelError(ValidationError):
    """
    L'exercice ne peut pas être archivé en Library sans difficulty_level
    (câblage Recommendation_Agent, clôture) — verrou distinct et cumulatif
    à IncompleteExerciseSetupError/PublicationNotConfirmedError ci-dessous
    (ceux-ci ne s'appliquent qu'à EXAM/HOMEWORK), jamais devinée
    automatiquement.
    """
    def __init__(self, exercise_id: uuid.UUID) -> None:
        super().__init__(
            f"L'exercice {exercise_id} ne peut pas être archivé en Library : "
            f"difficulty_level est obligatoire."
        )


class IncompleteExerciseSetupError(ValidationError):
    """
    L'exercice ne peut pas être publié : configuration incomplète.

    Levée par exercise_service.publish() avant toute transition de statut.
    Les quatre conditions bloquantes :
    1. Aucune question du tout (gap fermé : la création accepte désormais
       questions=[] pour permettre le remplissage exclusif par upload/OCR,
       cf. ExerciseCreateRequest — sans ce garde-fou, un exercice vide
       aurait pu passer la vérification de complétude trivialement, les
       trois boucles ci-dessous ne s'exécutant jamais sur une liste vide).
    2. Au moins une question sans barème.
    3. Au moins une question sans SolutionVariant is_reference=True.
    4. Au moins une ReasoningClarificationRequest en statut PENDING.
    """
    def __init__(
        self,
        exercise_id: uuid.UUID,
        no_questions: bool = False,
        missing_baremes: int = 0,
        missing_reference_variants: int = 0,
        pending_clarifications: int = 0,
    ) -> None:
        reasons = []
        if no_questions:
            reasons.append("aucune question définie")
        if missing_baremes:
            reasons.append(f"{missing_baremes} question(s) sans barème")
        if missing_reference_variants:
            reasons.append(f"{missing_reference_variants} question(s) sans variante de référence")
        if pending_clarifications:
            reasons.append(f"{pending_clarifications} clarification(s) en attente")
        detail = "; ".join(reasons) if reasons else "configuration incomplète"
        super().__init__(
            f"L'exercice {exercise_id} ne peut pas être publié : {detail}"
        )


class RecommendationNotFoundError(NotFoundError):
    """RecommendedExercise introuvable — câblage NotebookLM, §7 Partie 2/2 (endpoints vidéo/chat)."""
    def __init__(self, recommendation_id: uuid.UUID) -> None:
        super().__init__(f"Recommandation {recommendation_id} introuvable.")


class NotebookNotFoundError(NotFoundError):
    """
    Aucun StudentNotebook rattaché à cette recommandation — précondition
    des endpoints vidéo/chat (§7 Partie 2/2) : jamais une création
    silencieuse à ce moment-là (cf. contrainte explicite du ticket), le
    notebook n'existe que si la génération best-effort de Partie 1/2 a
    déjà réussi.
    """
    def __init__(self, recommendation_id: uuid.UUID) -> None:
        super().__init__(
            f"Aucun notebook NotebookLM n'existe pour la recommandation {recommendation_id} "
            f"(génération pas encore terminée, ou intégration indisponible)."
        )


class NotebookLMUnavailableError(ExternalServiceError):
    """Échec réel d'un appel synchrone NotebookLM (chat) — l'étudiant attend activement une réponse."""
    def __init__(self, notebook_id: str) -> None:
        super().__init__(
            f"NotebookLM est indisponible pour le moment (notebook {notebook_id}) — réessayez plus tard."
        )


class FlashcardsNotEligibleError(ValidationError):
    """
    Régénération de flashcards refusée — aucune weakness/identified_
    difficulty réelle sur le profil de compétences ACTUEL de l'étudiant
    pour ce module (même règle que la génération initiale, cf. docstring
    _has_real_weakness_data dans notebooklm_tasks.py — jamais de
    flashcards vides/génériques, y compris à la régénération).
    """
    def __init__(self, recommendation_id: uuid.UUID) -> None:
        super().__init__(
            f"Aucune difficulté identifiée pour ce module — pas de flashcards pertinentes "
            f"à générer pour la recommandation {recommendation_id}."
        )


class FeedbackReportNotFoundError(NotFoundError):
    """
    Aucun StudentFeedbackReport pour cette soumission — chantier Feedback_
    Agent (§7). Distinct de FeedbackNotFoundError (feedback PAR QUESTION,
    versionné, cf. feedback_version.py) : jamais confondu. Cas légitimes :
    feedback_node pas encore exécuté (soumission encore en cours de
    traitement), ou soumission jamais entrée dans la branche
    student_evaluation.
    """
    def __init__(self, submission_id: uuid.UUID) -> None:
        super().__init__(
            f"Aucun feedback n'a encore été généré pour la soumission {submission_id}."
        )

