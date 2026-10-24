"""
Schemas Pydantic pour Exercise/Question.

Décision de conception : Exercise est la racine d'agrégat (DDD) —
Question et Bareme lui appartiennent et sont TOUJOURS créés/lus ensemble
(§3 du résumé : "un seul formulaire"). Contrairement à academic_schemas.py
(entités indépendantes, on aplatit), ici on IMBRIQUE complètement à
l'intérieur de l'agrégat.

Les références VERS L'EXTÉRIEUR de l'agrégat (module, professeur) restent
aplaties (module_name, professor_full_name), même convention que
academic_schemas.py.

QuestionC2PCTSkill et sa validation "somme des poids = 100%" ont été
RETIRÉS de l'agrégat (décision actée) : les 7 compétences C2PCT
s'appliquent désormais systématiquement à chaque question, sans
configuration ni pondération — le barème reste la seule donnée fournie
par le professeur qui déterminait le score.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.models.assessment.exercise import ExerciseDifficulty, ExerciseStatus
from app.domain.models.competency.c2pct_scaffold import find_subquestion_by_id


# --- Bareme (imbriqué dans Question) ---

class CriterionCreate(BaseModel):
    label: str
    points: Decimal = Field(gt=0)


class CriterionRead(BaseModel):
    id: str  # UUID généré serveur, cf. convention Bareme.criteria
    label: str
    points: Decimal


class BaremeCreate(BaseModel):
    points: Decimal = Field(gt=0)
    criteria: list[CriterionCreate] = Field(default_factory=list)

    @field_validator("criteria")
    @classmethod
    def criteria_points_do_not_exceed_total(
        cls, criteria: list[CriterionCreate], info
    ) -> list[CriterionCreate]:
        total_points = info.data.get("points")
        if total_points is not None and criteria:
            criteria_sum = sum(c.points for c in criteria)
            if criteria_sum > total_points:
                raise ValueError(
                    f"La somme des critères ({criteria_sum}) dépasse le "
                    f"total du barème ({total_points})"
                )
        return criteria


class BaremeRead(BaseModel):
    id: uuid.UUID
    points: Decimal
    criteria: list[CriterionRead]

    model_config = {"from_attributes": True}


# --- Barème C2PCT natif (Cas 0), saisie manuelle ---
#
# Gap réel trouvé en usage (2026-09-04) : quand l'extraction IA du barème
# C2PCT natif (Extraction_Verification_Agent, Question.subquestion_points)
# manque un exercice (ex. tableau de barème jamais capturé par l'OCR sur une
# page dense), le SEUL recours de secours qui existait pour le professeur
# était `set_question_bareme` ci-dessus — mais celui-ci écrit dans le
# mécanisme CLASSIQUE (`Bareme`/`Criterion`, notation par critère), pas dans
# `subquestion_points` (notation par compétence C2PCT). Un professeur qui
# corrigeait ainsi un exercice C2PCT natif faisait, sans le savoir, basculer
# cette question sur le mauvais mode de calcul (Pedagogical_Evaluation_Agent
# ne verrait alors plus aucune sous-question chiffrée pour cette question).
# Ce schéma comble ce trou : saisie manuelle DIRECTEMENT dans
# `subquestion_points`, même mécanisme que l'extraction automatique.
class SubquestionPointsCreate(BaseModel):
    points: dict[str, Decimal] = Field(min_length=1)

    @field_validator("points")
    @classmethod
    def all_ids_are_official_subquestions(cls, points: dict[str, Decimal]) -> dict[str, Decimal]:
        for sq_id, value in points.items():
            if find_subquestion_by_id(sq_id) is None:
                raise ValueError(
                    f"'{sq_id}' n'est pas un identifiant de sous-question C2PCT officiel "
                    f"(ex. \"1.1\", \"3.2\", \"4\")."
                )
            if value <= 0:
                raise ValueError(f"Les points de la sous-question '{sq_id}' doivent être strictement positifs.")
        return points


# --- Section ---

class SectionCreate(BaseModel):
    order: int
    title: str


class SectionRead(BaseModel):
    id: uuid.UUID
    exercise_id: uuid.UUID
    order: int
    title: str

    model_config = {"from_attributes": True}


# --- Question ---
# Note : QuestionC2PCTSkillCreate/Read et la validation "somme des poids
# = 100%" ont été RETIRÉS (décisions actées) : les compétences C2PCT
# mobilisées sur une question sont dérivées des sous-questions officielles
# réellement couvertes (Question.covered_subquestions), sans configuration
# ni pondération par le professeur — plus rien à créer ou valider ici.

class QuestionCreate(BaseModel):
    order: int
    statement: str
    attachment_path: str | None = None
    section_id: uuid.UUID | None = None
    bareme: BaremeCreate | None = None  # optionnel : émerge de l'agent ou saisi par le prof


class SubquestionRead(BaseModel):
    """
    Une sous-question C2PCT officielle avec son contenu extrait (backlog_
    bugs_c2pct.md, structuration Question.subquestions, 2026-08-29).
    `official_title` n'est JAMAIS stocké en base — résolu ici depuis
    c2pct_scaffold (seule source de vérité), jamais dupliqué.
    """
    id: str
    official_title: str
    content: str


class QuestionRead(BaseModel):
    id: uuid.UUID
    exercise_id: uuid.UUID
    section_id: uuid.UUID | None = None
    order: int
    statement: str
    attachment_path: str | None
    bareme: BaremeRead | None
    # Ajouté pour la navigation de la Library (câblage Recommendation_Agent,
    # Phase 3) — sous-questions officielles réellement couvertes (mêmes
    # valeurs que Question.covered_subquestions, jamais recalculées), pour
    # que le client puisse voir/filtrer par compétence C2PCT sans requête
    # séparée (cf. c2pct_scaffold.get_competency_for_subquestion).
    covered_subquestions: list[str] = Field(default_factory=list)
    # 2026-08-29 — contenu structuré par sous-question officielle (cf.
    # SubquestionRead), pour un affichage en cartes côté frontend au lieu
    # du bloc `statement` continu. None si covered_subquestions était vide
    # ou si l'extraction verbatim a échoué (best-effort côté agent) — le
    # frontend retombe alors sur l'affichage du bloc `statement` complet.
    subquestions: list[SubquestionRead] | None = None
    # Bug réel corrigé (2026-09-03, test réel examen C2PCT à 3 exercices) :
    # le barème C2PCT natif (Cas 0, Extraction_Verification_Agent —
    # Question.subquestion_points, un point par sous-question officielle,
    # DISTINCT du barème classique `bareme` ci-dessus qui reste vide pour ce
    # type de document) était calculé et persisté correctement en base, mais
    # jamais exposé par cette réponse API — aucun moyen pour le professeur de
    # le voir, quelle que soit la qualité de l'extraction. None si ce
    # document n'utilise pas le barème C2PCT natif (mécanisme classique
    # `bareme` utilisé à la place).
    subquestion_points: dict[str, Decimal] | None = None

    model_config = {"from_attributes": True}

    @field_validator("subquestions", mode="before")
    @classmethod
    def _resolve_official_titles(cls, value):
        """
        Reçoit la valeur brute stockée en base (list[{"id", "content"}],
        jamais official_title) et l'enrichit depuis c2pct_scaffold avant
        validation du sous-modèle — jamais l'inverse (jamais un titre
        stocké en base qui pourrait diverger du référentiel). Un id
        inconnu du référentiel (ne devrait pas arriver, déjà filtré côté
        agent) est silencieusement omis, jamais un titre halluciné.
        """
        if not value:
            return None
        enriched = []
        for item in value:
            sq = find_subquestion_by_id(item["id"])
            if sq is None:
                continue
            enriched.append({"id": item["id"], "official_title": sq.label, "content": item["content"]})
        return enriched or None


# --- Exercise ---

class QuestionAddRequest(BaseModel):
    """Ajout d'une question à un exercice DRAFT déjà créé — order auto-calculé côté service."""
    statement: str


class QuestionUpdateRequest(BaseModel):
    statement: str


class ExerciseCreateRequest(BaseModel):
    """
    Le "formulaire unique" du §3 : le prof dépose sa correction/barème/C2PCT
    en une seule requête. Crée toujours en status=DRAFT — la publication
    (examen/devoir/library) est une action séparée, cf. ExercisePublishRequest.

    questions vide accepté (décision produit : la création ne collecte plus
    que les champs essentiels — module/titre/description — le remplissage
    des questions se fait exclusivement via le dépôt d'un document de
    référence scanné, cf. ExerciseRepository.add_structure, déjà conçue
    pour ajouter des Question à un Exercise DRAFT existant plutôt que
    create_with_questions). ExerciseService._check_completeness bloque
    toute publication tant qu'aucune question n'a été ajoutée (par l'OCR ou
    manuellement via POST .../questions, toujours disponible en secours).
    """
    module_id: uuid.UUID
    title: str
    description: str | None = None
    questions: list[QuestionCreate] = Field(default_factory=list)

    @field_validator("questions")
    @classmethod
    def question_orders_are_unique(
        cls, questions: list[QuestionCreate]
    ) -> list[QuestionCreate]:
        orders = [q.order for q in questions]
        if len(orders) != len(set(orders)):
            raise ValueError("Les numéros d'ordre des questions doivent être uniques")
        return questions


class ExercisePublishRequest(BaseModel):
    """
    Publication en mode examen/devoir : course_id et deadline deviennent
    obligatoires (contrairement au mode Library).
    """
    status: ExerciseStatus
    course_id: uuid.UUID | None = None
    deadline: datetime | None = None

    @model_validator(mode="after")
    def exam_and_homework_require_course_and_deadline(self) -> "ExercisePublishRequest":
        if self.status in (ExerciseStatus.PUBLISHED_AS_EXAM, ExerciseStatus.PUBLISHED_AS_HOMEWORK):
            if self.course_id is None:
                raise ValueError(f"course_id est obligatoire pour le statut {self.status}")
            if self.deadline is None:
                raise ValueError(f"deadline est obligatoire pour le statut {self.status}")
        return self


class ExerciseDeadlineUpdateRequest(BaseModel):
    """
    Report/avance de la deadline d'un examen/devoir DÉJÀ publié — jamais
    republier via ExercisePublishRequest pour ce seul besoin (cf. docstring
    ExerciseService.update_deadline).
    """
    deadline: datetime


class ExerciseArchiveToLibraryRequest(BaseModel):
    """
    Câblage Recommendation_Agent (clôture) — difficulty_level désormais
    OBLIGATOIRE au moment précis de l'archivage en Library (jamais deviné
    automatiquement, jamais optionnel à ce stade) : c'est le seul point où
    ce projet peut garantir qu'aucun exercice de la Library ne reste sans
    difficulté déclarée, même verrou de principe que course_id/deadline
    pour EXAM/HOMEWORK ci-dessus.
    """
    difficulty_level: ExerciseDifficulty


class ExerciseRead(BaseModel):
    id: uuid.UUID
    module_id: uuid.UUID
    module_name: str  # aplati, hors agrégat
    course_id: uuid.UUID | None
    created_by_professor_id: uuid.UUID
    professor_full_name: str  # aplati, hors agrégat
    title: str
    description: str | None
    status: ExerciseStatus
    deadline: datetime | None
    difficulty_level: ExerciseDifficulty | None
    sections: list[SectionRead] = Field(default_factory=list)
    questions: list[QuestionRead]  # imbriqué, dans l'agrégat

    model_config = {"from_attributes": True}


class PublicationReadinessQuestionSummary(BaseModel):
    """Résumé consultable par le professeur avant de confirmer la publication."""
    question_id: uuid.UUID
    order: int
    statement: str
    bareme_points: Decimal
    bareme_criteria: list[CriterionRead]
    reference_variant_summary: str  # reasoning_summary si disponible, sinon aperçu de content


class PublicationReadinessRead(BaseModel):
    """
    Réponse de POST /exercises/{id}/confirm-publication-readiness — échoie
    exactement ce qui vient d'être confirmé (le résumé + l'horodatage),
    pour que le professeur voie ce sur quoi porte sa confirmation.
    """
    exercise_id: uuid.UUID
    confirmed_at: datetime
    questions: list[PublicationReadinessQuestionSummary]


class ExerciseReferenceDocumentsCreate(BaseModel):
    """
    Dépôt du/des document(s) de correction du professeur.
    Utilisé par le Document_Structuring_Agent pour extraire les blocs
    TeacherCorrectionBlock et décomposer les questions / sections.

    document_paths : liste de chemins blob Azure (PDF, image).
    Plusieurs documents possibles si le prof dépose plusieurs pages
    séparément (ex. corrigé rédigé sur papier, scanné page par page).
    """
    exercise_id: uuid.UUID
    document_paths: list[str] = Field(min_length=1)