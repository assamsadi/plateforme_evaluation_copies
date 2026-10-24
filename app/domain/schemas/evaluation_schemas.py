"""
Schemas Pydantic pour Evaluation/EvaluationCriteria/Feedback/
FeedbackVersion/RecommendedExercise.

Deux agrégats ici : Evaluation (racine) + EvaluationCriteria (imbriqué),
et Feedback (racine, simple conteneur) + FeedbackVersion (imbriqué,
historique complet).

ClassicCriterion (exactitude/cohérence/complétude/justification) :
DÉPASSÉ par Pedagogical_Evaluation_Agent (Phase 4/4 du chantier C2PCT) —
conservé comme MÉTA-DONNÉE INFORMATIVE (héritage, lignes EvaluationCriteria
classiques), ne détermine PLUS le score final. C'est désormais la
répartition du barème entre compétences C2PCT réellement mobilisées
(covered_subquestions, lignes EvaluationCriteria "compétence",
competency_code/subquestion_detail) qui détermine score.

C2PCTObservedItem/c2pct_observed (RETIRÉS — câblage réparation
StudentCompetencyProfile) : ancienne granularité (7 compétences toujours
forcées, notées sur 100), jamais alimentée par le chemin actif — cf.
docstring Evaluation (evaluation.py) pour le détail complet. Remplacé par
un branchement direct sur CompetencyScoreDetail.success_rate
(Pedagogical_Evaluation_Agent), Niveau 1 uniquement, dans
EvaluationService.record_question_score.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.assessment.feedback_version import FeedbackAuthorType


# --- Evaluation ---

class ClassicCriterion(StrEnum):
    """
    Les 4 critères classiques — DÉPASSÉS par Pedagogical_Evaluation_Agent
    (Phase 4/4) : conservés comme méta-donnée informative (héritage),
    N'INFLUENCENT PLUS le score final. Cf. docstring module.
    """
    EXACTITUDE = "exactitude"
    COHERENCE = "coherence"
    COMPLETUDE = "completude"
    JUSTIFICATION = "justification"


class ClassicCriterionObservedItem(BaseModel):
    criterion: ClassicCriterion
    score: Decimal = Field(ge=0, le=100)
    justification: str


class SubquestionScoreDetailItem(BaseModel):
    """Une entrée de SubquestionDetailBlock.subquestions."""
    subquestion_id: str
    addressed: bool
    is_correct: bool | None
    source: str


class SubquestionDetailBlock(BaseModel):
    """
    Contenu exact de EvaluationCriteria.subquestion_detail (JSONB) —
    lignes compétence uniquement (Phase 4/4). Porte le détail brut par
    sous-question SANS multiplier les lignes EvaluationCriteria persistées.
    """
    subquestions: list[SubquestionScoreDetailItem]
    covered_count: int
    successful_count: int
    success_rate: Decimal


class EvaluationCriteriaRead(BaseModel):
    """
    Phase 4/4 — deux familles de lignes (cf. docstring EvaluationCriteria) :
    classique (criterion_id/criterion_label renseignés, competency_code/
    subquestion_detail=None) ou compétence (competency_code/subquestion_
    detail renseignés, criterion_id/criterion_label=None) — jamais les deux
    à la fois.
    """
    id: uuid.UUID
    # nullable (2026-09-06) : cf. EvaluationCriteria.bareme_id — None sur une
    # ligne compétence C2PCT-native (pas de Bareme classique à référencer).
    # Bug réel corrigé : ce schéma était resté non-optionnel après le
    # correctif du modèle, faisant planter GET .../evaluations (500) dès
    # qu'une ligne compétence existait — validation Pydantic, jamais
    # rattrapée avant la réponse HTTP.
    bareme_id: uuid.UUID | None
    criterion_id: str | None
    criterion_label: str | None  # aplati, résolu depuis Bareme.criteria (JSON) — None sur une ligne compétence
    points_awarded: Decimal
    comment: str | None
    competency_code: C2PCTSkillCode | None = None
    subquestion_detail: SubquestionDetailBlock | None = None

    model_config = {"from_attributes": True}


class EvaluationRead(BaseModel):
    id: uuid.UUID
    submission_id: uuid.UUID
    question_id: uuid.UUID
    question_order: int  # aplati
    score: Decimal
    classic_criteria_observed: list[ClassicCriterionObservedItem]
    criteria: list[EvaluationCriteriaRead]  # imbriqué, même agrégat

    model_config = {"from_attributes": True}


# --- Résultats étudiant (écran dédié "Mes résultats") ---
#
# Volontairement distinct de CopyReport/get_copy_report_for_professor —
# celui-ci est documenté comme "un outil de correction, pas un livrable
# pédagogique" (justifications techniques, criterion_lines bruts, jamais
# pensé pour un affichage étudiant). Ici : uniquement score/barème par
# question + total, la donnée dont un étudiant a besoin pour voir sa note.

class QuestionResultRead(BaseModel):
    question_id: uuid.UUID
    question_order: int
    # None tant qu'aucune Evaluation n'existe pour cette question (bug réel
    # constaté 2026-09-02 : une question jamais rattachée/notée disparaissait
    # purement et simplement de la liste, cf. is_graded ci-dessous) — jamais
    # 0 par défaut, pour ne pas laisser croire à une note réellement obtenue.
    score: Decimal | None
    max_score: Decimal
    is_graded: bool
    # None si is_graded=True (rien à justifier) ou si le service appelant n'a
    # pas de quoi le déterminer (cf. EvaluationService._extractions optionnel).
    # "no_student_answer" : aucun bloc de copie rattaché à cette question —
    # rien n'a été soumis. "pending_review" : du contenu existe mais la
    # notation n'a pas encore abouti (traitement en cours, ou question mise
    # en attente d'un arbitrage/clarification).
    not_graded_reason: Literal["no_student_answer", "pending_review"] | None = None
    # Justification RÉELLE de l'agent (Comparative_Evaluation_Agent.
    # ClarificationRequest.agent_question) quand not_graded_reason=
    # "pending_review" ET qu'une clarification BLOCKING existe pour CETTE
    # soumission précise (cf. ReasoningClarificationRequest.submission_id) —
    # jamais un texte générique. None si non applicable ou introuvable.
    blocking_justification: str | None = None


class SubmissionResultRead(BaseModel):
    submission_id: uuid.UUID
    exercise_title: str
    # Bug corrigé (2026-09-02, cas réel zainabsebhi) : max_score est
    # désormais le VRAI total de l'exercice (somme du barème de TOUTES les
    # questions), plus jamais restreint aux seules questions déjà notées —
    # l'ancien comportement faisait apparaître un barème de 10 au lieu de 20
    # dès qu'une question n'avait pas encore d'Evaluation (jamais rattachée
    # par Question_Attachment_Agent, notamment), gonflant silencieusement le
    # pourcentage affiché. total_score reste la somme des points RÉELLEMENT
    # obtenus (une question non notée contribue 0, pas plus). is_fully_graded
    # rend l'écart visible plutôt que de le masquer.
    total_score: Decimal
    max_score: Decimal
    is_fully_graded: bool
    questions: list[QuestionResultRead]


class StudentModuleSummaryRead(BaseModel):
    """
    Écran "Profil de compétence" (bloc infos étudiant) — agrégat pour UN
    module : combien de copies déposées/notées, et la note générale
    (total_score/max_score, somme sur toutes les soumissions ÉVALUÉES de ce
    module — même convention "seules les questions notées comptent" que
    SubmissionResultRead, appliquée ici par soumission).
    """
    student_id: uuid.UUID
    module_id: uuid.UUID
    total_submissions: int
    evaluated_submissions: int
    total_score: Decimal
    max_score: Decimal


# --- Feedback / FeedbackVersion ---

class FeedbackVersionCreate(BaseModel):
    """Le prof ajoute une nouvelle itération — author_type=TEACHER
    déduit côté service à partir de l'utilisateur authentifié, pas
    fourni par le client (jamais confiance dans une valeur envoyée
    par le front pour distinguer IA/humain)."""
    content: str


class FeedbackVersionRead(BaseModel):
    id: uuid.UUID
    feedback_id: uuid.UUID
    version_number: int
    content: str
    author_type: FeedbackAuthorType
    author_full_name: str | None  # aplati, None si author_type == AI

    model_config = {"from_attributes": True}


class FeedbackRead(BaseModel):
    id: uuid.UUID
    submission_id: uuid.UUID
    question_id: uuid.UUID
    versions: list[FeedbackVersionRead]  # imbriqué, même agrégat, historique complet

    model_config = {"from_attributes": True}


# --- RecommendedExercise ---

class RecommendedExerciseRead(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    module_id: uuid.UUID
    competency_code: str
    category: str  # "remediation" | "verification"
    status: str  # "active" | "superseded"
    # Nullable depuis le chantier Recommendation_Agent — la soumission dont
    # le traitement a DÉCLENCHÉ cette génération, jamais "causée par son
    # contenu" (cf. docstring modèle RecommendedExercise). None si générée
    # hors déclenchement par soumission.
    submission_id: uuid.UUID | None
    exercise_id: uuid.UUID
    exercise_title: str  # aplati
    # Aplati depuis Exercise.difficulty_level (même principe que exercise_
    # title ci-dessus, positionné dynamiquement par le service) — clôture
    # du chantier Recommendation_Agent : la difficulté était déjà utilisée
    # pour la sélection et mentionnée en texte libre dans `reason`, mais
    # jamais exposée comme champ structuré exploitable par le client
    # (badge, tri, filtre). None si l'exercice n'a jamais eu de difficulté
    # déclarée (cf. docstring ExerciseCompetencyCoverage).
    difficulty_level: str | None = None
    reason: str
    relevance_score: Decimal
    # Écran "Profil de compétence" (3e palier de recommandation, "faiblesse
    # persistante") — jointure à la lecture avec StudentCompetencyProfile
    # (student_id/module_id/competency_code déjà portés par cette ligne),
    # jamais un champ dupliqué en base : RecommendedExercise n'a que 2
    # catégories natives (remediation/verification, cf. docstring modèle) ;
    # ce 3e palier n'existe qu'en croisant avec is_persistent_weakness du
    # profil de compétence. False si aucun profil trouvé (jamais deviné).
    is_persistent_weakness: bool = False
    # Formats de sortie NotebookLM (§7, Partie 2/2) — tous aplatis depuis
    # le StudentNotebook rattaché (positionnés dynamiquement par le
    # service, jamais des colonnes ORM réelles — même principe
    # qu'exercise_title/difficulty_level ci-dessus). URLs régénérées à la
    # demande (SAS Azure, courte durée de vie), jamais persistées — None
    # tant que le format correspondant n'a pas été généré avec succès, ou
    # si aucun notebook n'a jamais été rattaché (intégration best-effort,
    # jamais un prérequis). video_overview_status toujours renseigné
    # (jamais None), contrairement aux URLs.
    audio_overview_url: str | None = None
    # Régénération à la demande (chantier "régénération NotebookLM") —
    # audio_overview_status/flashcards_status suivent désormais le même
    # cycle de vie explicite que video_overview_status (toujours renseigné,
    # jamais None), cf. docstring modèle StudentNotebook (GenerationStatus).
    audio_overview_status: str = "not_requested"
    flashcards_url: str | None = None
    flashcards_status: str = "not_requested"
    video_overview_url: str | None = None
    video_overview_status: str = "not_requested"
    # Jamais un lien Google direct — chemin vers notre propre API
    # (POST .../notebook-chat), cf. docstring NotebookLMService pour la
    # justification du choix d'accès. None si aucun notebook rattaché.
    notebook_chat_url: str | None = None

    model_config = {"from_attributes": True}


class VideoOverviewStateRead(BaseModel):
    """
    Réponse de POST .../generate-video — état actuel. Redéclenche
    désormais une régénération réelle depuis READY/FAILED (jamais depuis
    PENDING, dédoublonnage — cf. docstring RecommendationService.
    request_video_overview).
    """
    video_overview_status: str
    video_overview_url: str | None = None


class AudioOverviewStateRead(BaseModel):
    """Réponse de POST .../regenerate-audio — même contrat que VideoOverviewStateRead."""
    audio_overview_status: str
    audio_overview_url: str | None = None


class FlashcardsStateRead(BaseModel):
    """Réponse de POST .../regenerate-flashcards — même contrat que VideoOverviewStateRead."""
    flashcards_status: str
    flashcards_url: str | None = None


class NotebookChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class NotebookChatResponse(BaseModel):
    answer: str


# --- StudentFeedbackReport (chantier Feedback_Agent, §7) ---

class FeedbackReportRead(BaseModel):
    """
    Réponse de GET .../submissions/{submission_id}/feedback — texte
    socratique complet, prêt à être affiché tel quel (cf. Feedback_Agent).
    Construit explicitement en service (jamais via from_attributes) : le
    modèle ORM StudentFeedbackReport porte created_at/updated_at (Timestamp
    Mixin standard), pas un champ generated_at — cf. FeedbackReportService.
    """
    submission_id: uuid.UUID
    feedback_text: str
    competencies_addressed: list[str]
    generated_at: datetime