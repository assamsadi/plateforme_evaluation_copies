"""
Agent — Pedagogical_Evaluation_Agent (Phase 4/4 du chantier C2PCT).

Cet agent ne juge RIEN — il calcule, de façon strictement DÉTERMINISTE, à
partir de ce que les 3 agents précédents ont déjà tranché. Aucun appel LLM.

Entrées consommées telles quelles (aucune logique des 3 agents amont n'est
retouchée ici) :
  - Extraction_Verification_Agent (Phase 2/4) : Bareme.points (barème total
    de la question) + QuestionVerificationResult.covered_subquestions (id
    des sous-questions officielles C2PCT que le PROFESSEUR a réellement
    couvertes — seule autorité sur ce qui est mobilisé, jamais un total
    théorique de 15 substitué).
  - Comparative_Evaluation_Agent (Phase 3/4) : list[SubquestionJudgment]
    (addressed/is_correct par sous-question, jugées par rapport à la
    réponse de l'étudiant).

Formule (remplace la conception précédente, antérieure à la découverte de
la vraie méthodologie C2PCT/CHAABI, qui proposait un partage égal entre
compétences — cette version pondère proportionnellement au nombre RÉEL de
sous-questions couvertes par le professeur) :

  1. Regroupement de covered_subquestions par compétence parente, via
     c2pct_scaffold.get_competency_for_subquestion (module de référence,
     Phase 1 — jamais un modèle à imposer, un dictionnaire pour reconnaître).
  2. Part du barème par compétence — chantier barème C2PCT natif ("Cas 0",
     option (a) validée) : si le professeur a chiffré DIRECTEMENT TOUTES
     les sous-questions couvertes d'une compétence (QuestionVerification
     Result.subquestion_points, Extraction_Verification_Agent), part_
     competence = somme EXACTE de ces points, jamais recalculée. Le reste
     du barème (Bareme.points − Σ déjà alloué explicitement, jamais
     négatif) est réparti proportionnellement UNIQUEMENT entre les
     compétences non chiffrées, jamais divisé par nb_total_couvertes brut
     (double comptage sinon) :
       part_competence = budget_restant × (nb_couvertes_competence / nb_couvertes_restantes)
     Chiffrage PARTIEL d'une compétence (certaines sous-questions chiffrées,
     pas toutes) : jamais mélangé, cette compétence retombe entièrement en
     proportionnel — aucune valeur devinée pour compléter. subquestion_
     points absent/vide : dégénère exactement vers l'ancienne formule
     (budget_restant = Bareme.points, nb_couvertes_restantes =
     nb_total_couvertes), aucune régression sur les scénarios déjà validés.
  3. Taux de réussite par compétence — chantier notation graduée (Partie
     2/3, à partir de SubquestionJudgment.completion_ratio produit par
     Comparative_Evaluation_Agent, cf. son docstring) :
       taux_reussite = (Σ completion_ratio des sous-questions couvertes) / nb_couvertes_competence
     Une sous-question NOT_ADDRESSED (completion_ratio=None) contribue 0.0 à
     cette somme — jamais exclue du dénominateur (reste le total couvert
     par le prof), mais reste distinguable dans le détail persisté
     (subquestion_detail côté service), jamais absorbée silencieusement.
     Cas particulier ratio=1.0 partout (ancienne notation binaire) :
     formule strictement équivalente à l'ancienne (nb réussies / nb
     couvertes) — aucune régression sur les scénarios déjà validés.
  4. points_competence = part_competence × taux_reussite
     note_question = somme des points_competence sur toutes les compétences

Cas covered_subquestions vide : aucune base pour attribuer le moindre
point — note_question = 0, competency_scores = [] (jamais un total
théorique substitué à une couverture absente). Signal potentiel pour une
future clarification professeur, non construit ici (même principe que les
signaux non formalisés d'Extraction_Verification_Agent).

Agrégation sur toute la copie : DÉJÀ satisfaite par
EvaluationRepository.get_total_score_for_submission (SUM(Evaluation.score)
natif PostgreSQL, agnostique de la méthode de calcul en amont) — aucune
modification nécessaire, aucune méthode d'agrégation ajoutée ici.

Câblage réparation StudentCompetencyProfile : EvaluationService.record_
question_score consomme désormais directement le success_rate calculé ici
par compétence (Niveau 1, par question — c2pct_observed/C2PCTObservedItem
retirés, ancienne granularité jamais alimentée par le chemin actif) pour
mettre à jour StudentCompetencyProfile.mastery_level. Cet agent reste pur
calcul (aucune persistance ici) — l'agrégation Niveau 2 (toute la copie,
pondérée par sous-questions) et Niveau 3 (décroissance temporelle) restent
hors périmètre, rôle futur de Competency_Assessment_Agent (pas construit
ici).

Aucune persistance ici — même principe que tous les agents précédents de ce
projet : l'agent calcule, le service persiste (EvaluationService, adapté
séparément pour le nouveau schéma EvaluationCriteria).

Câblage copy_report (§0 Comparative_Evaluation_Agent : "chaque décision
vérifiable, traçable et contestable") — build_question_report() assemble
QuestionReport à partir d'un QuestionScoreResult DÉJÀ CALCULÉ par
evaluate_question() (jamais recalculé) et des DecisionEntry produites par
Comparative_Evaluation_Agent. Pur regroupement/présentation, aucune
nouvelle logique de notation. CopyReport (agrégat multi-questions, avec
overview) est assemblé à la LECTURE par EvaluationService.get_copy_report,
jamais par cet agent (qui ne voit qu'une question à la fois).

Calcul de note classique (ticket dédié, 2026-08-18) — tout ce qui précède
ne concerne QUE le mécanisme C2PCT natif (Cas 0). evaluate_question_classic()
couvre l'AUTRE mécanisme, jamais les deux sur une même question (cf.
discriminant de routage evaluation_node.py : présence de subquestion_points
POUR CETTE question) : le barème à critères (Cas 1/2/3), où
Comparative_Evaluation_Agent calcule déjà un score_ratio par critère (les
6+1 modes) mais où rien ne le transformait jusqu'ici en points. Même
discipline de calcul pur/déterministe, même _round_points, symétrie
volontaire avec evaluate_question()/build_question_report() ci-dessus
(ClassicQuestionEvaluationInput/ClassicQuestionScoreResult/
CriterionReportLine/build_question_report_classic).
"""
import logging
import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.agents.Comparative_Evaluation_Agent import DecisionEntry, SubquestionJudgment
from app.domain.models.competency.c2pct_scaffold import get_competency_for_subquestion
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode

logger = logging.getLogger(__name__)

_CENTS = Decimal("0.01")


def _round_points(value: Decimal) -> Decimal:
    """Arrondi cohérent avec la précision DB (Numeric(5,2)) — jamais un float."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Entrée / sortie
# ---------------------------------------------------------------------------

@dataclass
class QuestionEvaluationInput:
    question_id: uuid.UUID
    bareme_points: Decimal
    # Phase 2 — seule autorité sur ce qui est mobilisé (le professeur).
    covered_subquestions: list[str]
    # Phase 3 — jugements de la réponse étudiante, une entrée par id de
    # covered_subquestions (produits par Comparative_Evaluation_Agent).
    subquestion_judgments: list[SubquestionJudgment]
    # Chantier barème C2PCT natif — Cas 0 (PRIORITAIRE sur le calcul de
    # répartition proportionnelle ci-dessous, cf. evaluate_question) :
    # points donnés DIRECTEMENT par le professeur pour une sous-question
    # C2PCT (Extraction_Verification_Agent, jamais transité par
    # Comparative_Evaluation_Agent — cf. docstring comparative_evaluation_
    # node.py). None si aucun barème détaillé par sous-question n'a été
    # trouvé pour cette question, jamais un dict vide ambigu.
    subquestion_points: dict[str, Decimal] | None = None


@dataclass
class SubquestionScoreDetail:
    """Détail brut par sous-question — traçabilité fine sans multiplier les lignes persistées."""
    subquestion_id: str
    addressed: bool
    is_correct: bool | None
    source: str  # "reused_step_judgment" | "new_llm_judgment" | "missing_judgment"
    # Chantier notation graduée (Partie 2/3) — taux fin par sous-question,
    # None si addressed=False ou jugement manquant (même sémantique que
    # SubquestionJudgment.completion_ratio, jamais 0.0 pour une absence).
    completion_ratio: Decimal | None = None


@dataclass
class CompetencyScoreDetail:
    competency_code: C2PCTSkillCode
    covered_subquestion_ids: list[str] = field(default_factory=list)
    covered_count: int = 0
    successful_count: int = 0
    success_rate: Decimal = Decimal("0")  # taux_reussite, 0.0 à 1.0
    bareme_share: Decimal = Decimal("0")  # part_competence
    points_awarded: Decimal = Decimal("0")  # points_competence
    subquestion_detail: list[SubquestionScoreDetail] = field(default_factory=list)


@dataclass
class QuestionScoreResult:
    question_id: uuid.UUID
    total_score: Decimal  # note_question
    competency_scores: list[CompetencyScoreDetail] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Calcul de note classique (barème à critères, Cas 1/2/3 — jamais le
# mécanisme C2PCT natif ci-dessus sur une même question, cf. discriminant de
# routage evaluation_node.py : présence de subquestion_points POUR CETTE
# question). Σ(points_critère × score_ratio), déjà calculé critère par
# critère par Comparative_Evaluation_Agent (les 6+1 modes) mais jusqu'ici
# jamais transformé en points — evaluate_question_classic() ferme ce trou.
# ---------------------------------------------------------------------------

@dataclass
class ClassicCriterionJoinedInput:
    """
    Un critère du barème classique DÉJÀ JOINT à son verdict
    (Comparative_Evaluation_Agent) par criterion_id — la jointure elle-même
    est un pur assemblage de données faite côté evaluation_node.py (bareme.
    criteria x report.criterion_results, relayés via comparative_evaluation_
    node.py), pas une logique de calcul : elle n'a pas sa place dans cet
    agent, qui reste un calcul pur à partir d'entrées déjà résolues.
    """
    criterion_id: str
    label: str
    correction_mode: str
    points: Decimal
    # §2ter (Extraction_Verification_Agent.BaremeCriterionProposal.
    # disqualifying) — jamais transité par Comparative_Evaluation_Agent/
    # EvaluationRequest (qui ne juge que des ratios, jamais des points),
    # relais direct Bareme.criteria -> projection -> evaluation_node.py,
    # même principe que subquestion_points (chantier C2PCT natif).
    disqualifying: bool
    score_ratio: float
    is_satisfied: bool | None
    justification: str


@dataclass
class ClassicQuestionEvaluationInput:
    question_id: uuid.UUID
    criteria: list[ClassicCriterionJoinedInput]


@dataclass
class ClassicCriterionScoreDetail:
    """Détail par critère — équivalent classique de CompetencyScoreDetail ci-dessus."""
    criterion_id: str
    label: str
    correction_mode: str
    points_possible: Decimal
    score_ratio: float
    points_awarded: Decimal
    is_satisfied: bool | None
    justification: str


@dataclass
class ClassicQuestionScoreResult:
    question_id: uuid.UUID
    total_score: Decimal  # note_question
    criterion_scores: list[ClassicCriterionScoreDetail] = field(default_factory=list)
    # True si un critère disqualifying=True a été jugé non satisfait —
    # total_score forcé à 0 peu importe le reste (cf. evaluate_question_classic).
    disqualified: bool = False


# ---------------------------------------------------------------------------
# Câblage copy_report (§0 : "chaque décision vérifiable, traçable et
# contestable") — assemblage PUR à partir de QuestionScoreResult (déjà
# calculé par evaluate_question(), jamais retouché) et des DecisionEntry
# déjà produites par Comparative_Evaluation_Agent. Aucun nouveau calcul de
# note/taux/part ici, uniquement du regroupement et de la présentation.
# ---------------------------------------------------------------------------

@dataclass
class CompetencyReportLine:
    competency: C2PCTSkillCode
    subquestions_covered_by_professor: int
    subquestions_succeeded_by_student: int
    bareme_share: Decimal
    points_awarded: Decimal
    # Chantier notation graduée (Partie 2/3) — taux gradué (0.0 à 1.0),
    # complète subquestions_succeeded_by_student (compte brut des sous-
    # questions PLEINEMENT réussies) pour un affichage fin, ex. "88% de
    # réussite sur cette compétence" plutôt qu'un simple "4/5".
    success_rate: Decimal = Decimal("0")
    # Uniquement les DecisionEntry non triviales concernant CETTE compétence
    # (cf. DecisionEntry — jamais une par sous-question systématiquement).
    decisions: list[DecisionEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "competency": self.competency.value,
            "subquestions_covered_by_professor": self.subquestions_covered_by_professor,
            "subquestions_succeeded_by_student": self.subquestions_succeeded_by_student,
            "bareme_share": str(self.bareme_share),
            "points_awarded": str(self.points_awarded),
            "success_rate": str(self.success_rate),
            "decisions": [d.to_dict() for d in self.decisions],
        }

    @staticmethod
    def from_dict(d: dict) -> "CompetencyReportLine":
        # Repli défensif — QuestionReport persistés avant ce chantier n'ont
        # pas cette clé : approximé depuis le compte binaire (non gradué,
        # mais jamais un KeyError sur une donnée historique légitime).
        covered = d["subquestions_covered_by_professor"]
        succeeded = d["subquestions_succeeded_by_student"]
        default_rate = str(Decimal(succeeded) / Decimal(covered)) if covered else "0"
        return CompetencyReportLine(
            competency=C2PCTSkillCode(d["competency"]),
            subquestions_covered_by_professor=covered,
            subquestions_succeeded_by_student=succeeded,
            bareme_share=Decimal(d["bareme_share"]),
            points_awarded=Decimal(d["points_awarded"]),
            success_rate=Decimal(d.get("success_rate", default_rate)),
            decisions=[DecisionEntry.from_dict(e) for e in d.get("decisions", [])],
        )


@dataclass
class CriterionReportLine:
    """
    Équivalent classique de CompetencyReportLine ci-dessus, pour la
    traçabilité copy_report du mécanisme à critères. Pas de champ
    `decisions` (contrairement à CompetencyReportLine) : DecisionEntry.
    competency est un champ OBLIGATOIRE (C2PCTSkillCode, pas de défaut) —
    forcer une valeur factice pour un critère classique, qui n'a pas de
    compétence C2PCT associée, produirait une donnée inventée plutôt
    qu'une absence explicite.
    """
    criterion_id: str
    label: str
    correction_mode: str
    points_possible: Decimal
    score_ratio: float
    points_awarded: Decimal
    is_satisfied: bool | None
    justification: str

    def to_dict(self) -> dict:
        return {
            "criterion_id": self.criterion_id,
            "label": self.label,
            "correction_mode": self.correction_mode,
            "points_possible": str(self.points_possible),
            "score_ratio": self.score_ratio,
            "points_awarded": str(self.points_awarded),
            "is_satisfied": self.is_satisfied,
            "justification": self.justification,
        }

    @staticmethod
    def from_dict(d: dict) -> "CriterionReportLine":
        return CriterionReportLine(
            criterion_id=d["criterion_id"],
            label=d["label"],
            correction_mode=d["correction_mode"],
            points_possible=Decimal(d["points_possible"]),
            score_ratio=d["score_ratio"],
            points_awarded=Decimal(d["points_awarded"]),
            is_satisfied=d["is_satisfied"],
            justification=d["justification"],
        )


@dataclass
class QuestionReport:
    question_id: uuid.UUID
    note: Decimal
    bareme_points: Decimal
    # Une question donnée ne remplit JAMAIS les deux (cf. discriminant de
    # routage evaluation_node.py) — mais le dataclass porte les deux champs,
    # l'un restant vide selon le mécanisme réellement utilisé pour cette question.
    competency_lines: list[CompetencyReportLine] = field(default_factory=list)
    criterion_lines: list[CriterionReportLine] = field(default_factory=list)
    # Relayé depuis la projection (comparative_evaluation_node, cf. son
    # docstring) — None si mandated_method n'était pas renseigné pour cette
    # question (rien à vérifier, jamais déduit).
    consigne_respected: bool | None = None

    def to_dict(self) -> dict:
        return {
            "question_id": str(self.question_id),
            "note": str(self.note),
            "bareme_points": str(self.bareme_points),
            "competency_lines": [c.to_dict() for c in self.competency_lines],
            "criterion_lines": [c.to_dict() for c in self.criterion_lines],
            "consigne_respected": self.consigne_respected,
        }

    @staticmethod
    def from_dict(d: dict) -> "QuestionReport":
        return QuestionReport(
            question_id=uuid.UUID(d["question_id"]),
            note=Decimal(d["note"]),
            bareme_points=Decimal(d["bareme_points"]),
            competency_lines=[CompetencyReportLine.from_dict(c) for c in d.get("competency_lines", [])],
            criterion_lines=[CriterionReportLine.from_dict(c) for c in d.get("criterion_lines", [])],
            consigne_respected=d.get("consigne_respected"),
        )


@dataclass
class CopyReport:
    """
    Assemblé par EvaluationService.get_copy_report() (jamais par cet agent
    lui-même, qui ne voit qu'une question à la fois) en agrégeant les
    QuestionReport persistés sur toutes les Evaluation d'une soumission —
    même principe que EvaluationRepository.get_total_score_for_submission
    (agrégation à la LECTURE, jamais un document dupliqué stocké une
    deuxième fois au niveau soumission, cf. docstring evaluation_service.py).
    """
    submission_id: uuid.UUID
    overview: dict
    questions: list[QuestionReport] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class PedagogicalEvaluationAgent:
    """Calcul déterministe pur — aucun appel LLM, aucun jugement de fond."""

    AGENT_NAME = "Pedagogical_Evaluation_Agent"

    def evaluate_question(self, request: QuestionEvaluationInput) -> QuestionScoreResult:
        covered = request.covered_subquestions
        if not covered:
            # Aucune base pour attribuer le moindre point — jamais un total
            # théorique substitué à une couverture absente (cf. docstring module).
            return QuestionScoreResult(
                question_id=request.question_id,
                total_score=Decimal("0.00"),
                competency_scores=[],
            )

        judgment_by_id = {j.subquestion_id: j for j in request.subquestion_judgments}

        # 1. Regroupement par compétence parente (module de référence, jamais deviné).
        ids_by_competency: dict[C2PCTSkillCode, list[str]] = {}
        for sq_id in covered:
            skill = get_competency_for_subquestion(sq_id)
            if skill is None:
                # id inconnu du module de référence : jamais deviné, ignoré
                # individuellement — n'entraîne jamais un échec de tout le calcul.
                continue
            ids_by_competency.setdefault(skill, []).append(sq_id)

        # nb_total_couvertes = uniquement les id RÉELLEMENT résolus à une
        # compétence (cohérent avec le numérateur ci-dessous, jamais
        # compter un id qu'on a par ailleurs exclu du regroupement).
        nb_total_couvertes = sum(len(ids) for ids in ids_by_competency.values())
        if nb_total_couvertes == 0:
            return QuestionScoreResult(
                question_id=request.question_id,
                total_score=Decimal("0.00"),
                competency_scores=[],
            )

        # Chantier barème C2PCT natif — Cas 0 (PRIORITAIRE, option (a)
        # validée) : une compétence est "chiffrée" si TOUTES ses sous-
        # questions couvertes sont présentes comme clés dans subquestion_
        # points (chiffrage partiel = jamais utilisé, cf. ci-dessous —
        # jamais un mélange deviné à l'intérieur d'une même compétence).
        # bareme_share des compétences chiffrées = somme EXACTE donnée par
        # le prof, jamais le calcul proportionnel. Le RESTE du barème
        # (bareme_points - Σ déjà alloué explicitement, jamais négatif) est
        # réparti proportionnellement entre les compétences NON chiffrées
        # UNIQUEMENT — jamais divisé par nb_total_couvertes qui inclurait à
        # tort les sous-questions déjà payées explicitement (double
        # comptage). Cas subquestion_points=None ou aucune compétence
        # entièrement chiffrée -> dégénère exactement vers l'ancien calcul
        # (remaining_budget=bareme_points, remaining_count=nb_total_couvertes).
        subquestion_points = request.subquestion_points or {}
        priced_skills: set[C2PCTSkillCode] = {
            skill for skill, ids in ids_by_competency.items()
            if ids and all(sq_id in subquestion_points for sq_id in ids)
        }
        explicit_total = sum(
            (subquestion_points[sq_id] for skill in priced_skills for sq_id in ids_by_competency[skill]),
            Decimal("0"),
        )
        if explicit_total > request.bareme_points:
            # Jamais un budget négatif — le reste (compétences non
            # chiffrées) retombe à 0 plutôt qu'un point théorique inventé.
            # Anomalie professeur/extraction réelle, signalée mais jamais
            # bloquante (même discipline que les autres signaux "seulement
            # loggés" de ce projet).
            logger.warning(
                "Question %s : la somme des points chiffrés par sous-question C2PCT (%s) "
                "dépasse le barème total (%s) — reste plafonné à 0 pour les compétences "
                "non chiffrées.",
                request.question_id, explicit_total, request.bareme_points,
            )
        remaining_budget = max(Decimal("0"), request.bareme_points - explicit_total)
        remaining_count = sum(
            len(ids) for skill, ids in ids_by_competency.items() if skill not in priced_skills
        )

        competency_scores: list[CompetencyScoreDetail] = []
        for skill in C2PCTSkillCode:  # ordre déterministe
            ids_for_skill = ids_by_competency.get(skill)
            if not ids_for_skill:
                continue

            covered_count = len(ids_for_skill)

            detail: list[SubquestionScoreDetail] = []
            successful_count = 0
            # Chantier notation graduée (Partie 2/3) — somme des completion_
            # ratio, None (addressed=False OU jugement manquant) traité comme
            # 0.0 dans la somme, JAMAIS exclu du dénominateur (covered_count
            # reste le total couvert par le prof, même principe que l'ancien
            # comptage binaire). is_correct/successful_count restent calculés
            # à l'identique (comptage des sous-questions PLEINEMENT réussies,
            # completion_ratio == 1.0 par construction, cf. Comparative_
            # Evaluation_Agent) — utile pour l'affichage, ne remplace pas
            # ratio_sum dans le calcul du taux.
            ratio_sum = Decimal("0")
            for sq_id in ids_for_skill:
                judgment = judgment_by_id.get(sq_id)
                if judgment is None:
                    # Jamais deviné un succès : un id couvert par le prof
                    # mais sans jugement produit (ne devrait pas arriver en
                    # usage normal, cf. Comparative_Evaluation_Agent) est
                    # traité aussi conservativement qu'une absence.
                    detail.append(SubquestionScoreDetail(
                        subquestion_id=sq_id, addressed=False, is_correct=None,
                        source="missing_judgment", completion_ratio=None,
                    ))
                    continue
                if judgment.addressed and judgment.is_correct:
                    successful_count += 1
                if judgment.addressed and judgment.completion_ratio is not None:
                    ratio_sum += judgment.completion_ratio
                # else : addressed=False (ou, défensivement, addressed=True
                # sans completion_ratio — ne devrait jamais arriver en usage
                # réel) -> contribue 0.0 à la somme, jamais deviné.
                detail.append(SubquestionScoreDetail(
                    subquestion_id=sq_id,
                    addressed=judgment.addressed,
                    is_correct=judgment.is_correct,
                    source=judgment.source,
                    completion_ratio=judgment.completion_ratio,
                ))

            # 2. Part du barème — Cas 0 (chiffrage explicite, somme exacte)
            # si cette compétence est entièrement chiffrée, sinon calcul
            # proportionnel classique MAIS sur le budget restant/le compte
            # restant (jamais bareme_points/nb_total_couvertes bruts dès
            # qu'au moins une compétence de la question est chiffrée — cf.
            # remaining_budget/remaining_count ci-dessus).
            if skill in priced_skills:
                bareme_share = sum((subquestion_points[sq_id] for sq_id in ids_for_skill), Decimal("0"))
            elif remaining_count == 0:
                # Défensif — ne devrait pas arriver (skill non chiffrée
                # implique ids_for_skill contribue à remaining_count), mais
                # jamais une division par zéro si ça se produit malgré tout.
                bareme_share = Decimal("0")
            else:
                bareme_share = remaining_budget * Decimal(covered_count) / Decimal(remaining_count)
            # 3. Taux de réussite gradué — somme des completion_ratio (0.0
            #    pour une absence) / total couvert par le prof. Cas
            #    particulier ratio=1.0 partout -> formule binaire d'origine
            #    inchangée (mêmes résultats numériques que les scénarios de
            #    référence déjà validés).
            success_rate = ratio_sum / Decimal(covered_count)
            # 4. Points obtenus par compétence.
            points_awarded = _round_points(bareme_share * success_rate)

            competency_scores.append(
                CompetencyScoreDetail(
                    competency_code=skill,
                    covered_subquestion_ids=ids_for_skill,
                    covered_count=covered_count,
                    successful_count=successful_count,
                    success_rate=success_rate,
                    bareme_share=_round_points(bareme_share),
                    points_awarded=points_awarded,
                    subquestion_detail=detail,
                )
            )

        total_score = sum((c.points_awarded for c in competency_scores), Decimal("0.00"))

        return QuestionScoreResult(
            question_id=request.question_id,
            total_score=total_score,
            competency_scores=competency_scores,
        )

    def evaluate_question_classic(
        self, request: ClassicQuestionEvaluationInput,
    ) -> ClassicQuestionScoreResult:
        """
        Mécanisme classique (barème à critères) — Σ(points_critère ×
        score_ratio), jamais un score continu redemandé au LLM : score_ratio
        est déjà calculé, critère par critère, par Comparative_Evaluation_
        Agent (les 6+1 modes, cf. CriterionEvaluationResult.score_ratio).

        Un critère disqualifying=True jugé non satisfait invalide la
        TOTALITÉ des points de la question, peu importe le reste (cf.
        docstring originale de BaremeCriterionProposal.disqualifying) —
        vérifié AVANT toute somme.
        """
        disqualified = any(
            c.disqualifying and c.is_satisfied is False for c in request.criteria
        )

        if disqualified:
            # points_awarded mis à 0 par cohérence avec total_score, même si
            # score_ratio individuel de chaque critère reste renseigné
            # (informatif pour le rapport) — jamais un point accordé sur une
            # question disqualifiée.
            criterion_scores = [
                ClassicCriterionScoreDetail(
                    criterion_id=c.criterion_id,
                    label=c.label,
                    correction_mode=c.correction_mode,
                    points_possible=c.points,
                    score_ratio=c.score_ratio,
                    points_awarded=Decimal("0.00"),
                    is_satisfied=c.is_satisfied,
                    justification=c.justification,
                )
                for c in request.criteria
            ]
            return ClassicQuestionScoreResult(
                question_id=request.question_id,
                total_score=Decimal("0.00"),
                criterion_scores=criterion_scores,
                disqualified=True,
            )

        criterion_scores = [
            ClassicCriterionScoreDetail(
                criterion_id=c.criterion_id,
                label=c.label,
                correction_mode=c.correction_mode,
                points_possible=c.points,
                score_ratio=c.score_ratio,
                points_awarded=_round_points(c.points * Decimal(str(c.score_ratio))),
                is_satisfied=c.is_satisfied,
                justification=c.justification,
            )
            for c in request.criteria
        ]
        total_score = _round_points(
            sum((c.points_awarded for c in criterion_scores), Decimal("0"))
        )

        return ClassicQuestionScoreResult(
            question_id=request.question_id,
            total_score=total_score,
            criterion_scores=criterion_scores,
        )

    @staticmethod
    def build_question_report(
        question_id: uuid.UUID,
        bareme_points: Decimal,
        score_result: QuestionScoreResult,
        decision_entries: list[DecisionEntry],
        consigne_respected: bool | None = None,
    ) -> QuestionReport:
        """
        Câblage copy_report — assemblage PUR, aucun recalcul : score_result
        est déjà produit par evaluate_question() (intouché), decision_entries
        déjà produites par Comparative_Evaluation_Agent. Regroupe uniquement
        les decision_entries par compétence (une DecisionEntry par
        compétence, jamais dupliquée entre lignes).
        """
        entries_by_competency: dict[C2PCTSkillCode, list[DecisionEntry]] = {}
        for entry in decision_entries:
            entries_by_competency.setdefault(entry.competency, []).append(entry)

        lines = [
            CompetencyReportLine(
                competency=c.competency_code,
                subquestions_covered_by_professor=c.covered_count,
                subquestions_succeeded_by_student=c.successful_count,
                bareme_share=c.bareme_share,
                points_awarded=c.points_awarded,
                success_rate=c.success_rate,
                decisions=entries_by_competency.get(c.competency_code, []),
            )
            for c in score_result.competency_scores
        ]

        return QuestionReport(
            question_id=question_id,
            note=score_result.total_score,
            bareme_points=bareme_points,
            competency_lines=lines,
            consigne_respected=consigne_respected,
        )

    @staticmethod
    def build_question_report_classic(
        question_id: uuid.UUID,
        bareme_points: Decimal,
        score_result: ClassicQuestionScoreResult,
        consigne_respected: bool | None = None,
    ) -> QuestionReport:
        """
        Équivalent classique de build_question_report ci-dessus — assemblage
        PUR, aucun recalcul : score_result déjà produit par
        evaluate_question_classic() (intouché). Pas de decision_entries ici
        (mécanisme C2PCT uniquement, cf. CriterionReportLine) : le mécanisme
        classique n'alimente jamais le profil de compétence C2PCT, c'est
        attendu, pas un manque.
        """
        lines = [
            CriterionReportLine(
                criterion_id=c.criterion_id,
                label=c.label,
                correction_mode=c.correction_mode,
                points_possible=c.points_possible,
                score_ratio=c.score_ratio,
                points_awarded=c.points_awarded,
                is_satisfied=c.is_satisfied,
                justification=c.justification,
            )
            for c in score_result.criterion_scores
        ]

        return QuestionReport(
            question_id=question_id,
            note=score_result.total_score,
            bareme_points=bareme_points,
            criterion_lines=lines,
            consigne_respected=consigne_respected,
        )
