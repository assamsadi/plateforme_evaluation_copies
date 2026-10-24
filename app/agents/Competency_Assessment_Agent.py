"""
Agent — Competency_Assessment_Agent (Partie 1/2, chantier C2PCT).

Transforme les résultats bruts de correction (déjà persistés par
Pedagogical_Evaluation_Agent/EvaluationService, jamais recalculés) en un
profil de compétences agrégé, à deux échelles :

  - Niveau 2 (compute_submission_observations) : par COPIE ENTIÈRE,
    pondéré par le nombre RÉEL de sous-questions couvertes/réussies sur
    toutes les questions de la soumission — JAMAIS une moyenne simple des
    taux par question (exemple de référence : ALGORITHMIC_STRUCTURING sur
    Q2 (3 couvertes, 2 réussies) + Q5 (2 couvertes, 1 réussie) + Q7
    (4 couvertes, 4 réussies) = (2+1+4)/(3+2+4) = 7/9 ≈ 0.7778, jamais la
    moyenne de 67%/50%/100% = 72%).

  - Niveau 3 (build_competency_line) : dans le temps, décroissance
    exponentielle sur l'historique des observations Niveau 2 d'un module
    (poids_i = decay_factor^i, i=0 pour l'observation la plus récente) —
    remplace l'ancienne moyenne mobile simple d'EvaluationService (retirée,
    cf. son docstring : deux mécanismes concurrents auraient écrit
    StudentCompetencyProfile depuis deux sources de vérité contradictoires).

Cet agent NE PREND AUCUNE DÉCISION PÉDAGOGIQUE — il mesure et explique où
en est l'étudiant, jamais ce qu'il faut lui recommander (rôle futur d'un
Feedback_Agent/Recommendation_Agent, PAS construit ici). AUCUN appel LLM —
calcul et agrégation déterministes uniquement, à partir de données déjà
produites par les agents amont : SubquestionJudgment (via EvaluationCriteria.
subquestion_detail, Pedagogical_Evaluation_Agent) et DecisionEntry (via
Evaluation.copy_report_detail, Comparative_Evaluation_Agent).

Pur — ne touche jamais la DB (agent calcule, CompetencyAssessmentService
persiste, même principe "agent calcule, service persiste" que tous les
agents précédents de ce projet).

Champs enrichis (subquestions_concerned/evidence_questions/strengths/
weaknesses/identified_difficulties/confidence_level) : gardés focalisés
sur ce qui apporte une vraie valeur à de futurs Feedback_Agent/
Recommendation_Agent (décision produit) — tous dérivés déterministiquement
de données déjà existantes, AUCUN nouveau texte généré. is_persistent_
weakness conservé également (signal directement exploitable par un futur
Recommendation_Agent pour prioriser).
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.domain.models.competency.c2pct_scaffold import find_subquestion_by_id
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode

# Plafond déterministe sur les listes enrichies (strengths/weaknesses/
# identified_difficulties) — évite une liste sans borne au fil du temps,
# documenté ici plutôt qu'un magic number silencieux.
_MAX_ENRICHED_ITEMS = 5


def _round(value: Decimal, places: Decimal = Decimal("0.01")) -> Decimal:
    """Arrondi cohérent avec la précision DB, jamais un float."""
    return value.quantize(places, rounding=ROUND_HALF_UP)


def _outcome_completion_ratio(outcome: dict) -> Decimal:
    """
    Chantier notation graduée (Partie 3/3) — taux gradué d'un outcome de
    sous-question, toujours 0.0 si addressed=False (jamais deviné sur une
    absence). Repli sur is_correct binaire (1.0/0.0) si completion_ratio
    est absent du dict — EvaluationCriteria.subquestion_detail persisté
    AVANT ce chantier (Parties 1/2) n'a pas cette clé, jamais un KeyError
    sur une donnée historique légitime.
    """
    if not outcome.get("addressed"):
        return Decimal("0")
    raw_ratio = outcome.get("completion_ratio")
    if raw_ratio is not None:
        return Decimal(str(raw_ratio))
    return Decimal("1") if outcome.get("is_correct") is True else Decimal("0")


# ---------------------------------------------------------------------------
# Entrées Niveau 2 — assemblées par CompetencyAssessmentService depuis
# EvaluationCriteria (subquestion_detail)/Evaluation (copy_report_detail),
# jamais recalculées.
# ---------------------------------------------------------------------------

@dataclass
class QuestionCompetencyContribution:
    """Une ligne EvaluationCriteria 'compétence' (competency_code non NULL) pour une question donnée."""
    question_id: uuid.UUID
    competency: C2PCTSkillCode
    covered_count: int
    successful_count: int
    # [{"subquestion_id": str, "addressed": bool, "is_correct": bool|None}]
    # — TOUTES les sous-questions, y compris les succès triviaux (absents
    # de decision_reasons/DecisionEntry), nécessaire pour dériver `strengths`.
    subquestion_outcomes: list[dict] = field(default_factory=list)
    # [{"subquestion_id": str, "decision": str, "reason": str}] — UNIQUEMENT
    # les DecisionEntry non triviales déjà produites par Comparative_
    # Evaluation_Agent (cf. Evaluation.copy_report_detail).
    decision_reasons: list[dict] = field(default_factory=list)


@dataclass
class SubmissionCompetencyObservation:
    """Sortie de compute_submission_observations — une par compétence RÉELLEMENT touchée dans CETTE soumission."""
    competency: C2PCTSkillCode
    performance_copie: Decimal  # 0.0-1.0
    subquestions_covered_count: int
    subquestions_succeeded_count: int
    question_ids: list[uuid.UUID] = field(default_factory=list)
    subquestion_outcomes: list[dict] = field(default_factory=list)
    decision_reasons: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Entrées Niveau 3 — reflètent une ligne StudentCompetencyObservation déjà
# persistée (l'historique lu par le service, jamais recalculé depuis
# Evaluation/EvaluationCriteria à chaque lecture).
# ---------------------------------------------------------------------------

@dataclass
class CompetencyObservationRecord:
    performance_copie: Decimal
    subquestions_covered_count: int
    subquestions_succeeded_count: int
    question_ids: list[uuid.UUID]
    subquestion_outcomes: list[dict]
    decision_reasons: list[dict]
    created_at: datetime


# ---------------------------------------------------------------------------
# Sortie
# ---------------------------------------------------------------------------

@dataclass
class CompetencyProfileLine:
    competency: C2PCTSkillCode
    mastery_level: Decimal  # 0-100, Niveau 3 (décroissance exponentielle)
    trend: Literal["IMPROVING", "DECLINING", "STABLE", "INSUFFICIENT_DATA"]
    evaluations_count: int
    subquestions_concerned: list[str] = field(default_factory=list)
    evidence_questions: list[uuid.UUID] = field(default_factory=list)
    identified_difficulties: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    confidence_level: Decimal = Decimal("0")
    is_persistent_weakness: bool = False


@dataclass
class StudentCompetencyReport:
    student_id: uuid.UUID
    module_id: uuid.UUID
    generated_at: datetime
    # Une ligne par compétence ayant AU MOINS une observation — jamais les
    # 7 forcées si certaines n'ont jamais été mobilisées pour cet étudiant
    # dans ce module.
    lines: list[CompetencyProfileLine] = field(default_factory=list)


def _rank_subquestion_pattern(
    observations: list[CompetencyObservationRecord], want_success: bool,
    strength_threshold: Decimal, weakness_threshold: Decimal,
) -> list[str]:
    """
    Chantier notation graduée (Partie 3/3) — strengths (want_success=True) :
    subquestion_id où addressed=True ET completion_ratio >= strength_
    threshold apparaît AU MOINS 2 FOIS ("de façon répétée") sur l'historique.
    weaknesses (want_success=False) : addressed=False OU completion_ratio <
    weakness_threshold, même seuil de répétition — addressed=False compte
    TOUJOURS comme un échec, indépendamment du seuil (jamais un ratio deviné
    sur une absence). completion_ratio absent (données antérieures à ce
    chantier) : repli sur is_correct binaire, cf. _outcome_completion_ratio.
    Jamais un texte inventé — formaté "{id} ({label})" via c2pct_scaffold
    (référence déjà existante), trié par fréquence décroissante, plafonné à
    _MAX_ENRICHED_ITEMS.
    """
    counts: dict[str, int] = {}
    for obs in observations:
        for outcome in obs.subquestion_outcomes:
            sq_id = outcome["subquestion_id"]
            addressed = bool(outcome.get("addressed"))
            if want_success:
                matches = addressed and _outcome_completion_ratio(outcome) >= strength_threshold
            else:
                matches = (not addressed) or _outcome_completion_ratio(outcome) < weakness_threshold
            if matches:
                counts[sq_id] = counts.get(sq_id, 0) + 1

    repeated = [(sq_id, n) for sq_id, n in counts.items() if n >= 2]
    repeated.sort(key=lambda pair: pair[1], reverse=True)

    labels: list[str] = []
    for sq_id, _count in repeated[:_MAX_ENRICHED_ITEMS]:
        sq = find_subquestion_by_id(sq_id)
        labels.append(f"{sq_id} ({sq.label})" if sq is not None else sq_id)
    return labels


def _rank_difficulties(observations: list[CompetencyObservationRecord]) -> list[str]:
    """
    identified_difficulties — textes DecisionEntry.reason DÉJÀ EXISTANTS
    (jamais un nouveau texte généré), groupés par (subquestion_id,
    decision), le texte le PLUS RÉCENT de chaque groupe retenu (observations
    supposé trié par récence décroissante), trié par fréquence décroissante,
    plafonné à _MAX_ENRICHED_ITEMS.
    """
    groups: dict[tuple[str, str], list[str]] = {}
    for obs in observations:  # du plus récent au plus ancien
        for entry in obs.decision_reasons:
            key = (entry["subquestion_id"], entry["decision"])
            groups.setdefault(key, []).append(entry["reason"])

    ranked = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
    return [texts[0] for _key, texts in ranked[:_MAX_ENRICHED_ITEMS]]


class CompetencyAssessmentAgent:
    """Calcul déterministe pur — aucun appel LLM, aucune décision pédagogique, aucun accès DB."""

    AGENT_NAME = "Competency_Assessment_Agent"

    @staticmethod
    def compute_submission_observations(
        contributions: list[QuestionCompetencyContribution],
    ) -> list[SubmissionCompetencyObservation]:
        """
        Niveau 2 — regroupe les contributions par compétence (une soumission
        peut mobiliser une même compétence sur plusieurs questions), pondéré
        par le nombre RÉEL de sous-questions (jamais une moyenne simple des
        taux par question — cf. docstring module pour l'exemple de référence).
        """
        by_competency: dict[C2PCTSkillCode, list[QuestionCompetencyContribution]] = {}
        for c in contributions:
            by_competency.setdefault(c.competency, []).append(c)

        observations: list[SubmissionCompetencyObservation] = []
        for competency, group in by_competency.items():
            total_covered = sum(c.covered_count for c in group)
            total_successful = sum(c.successful_count for c in group)
            if total_covered == 0:
                continue  # jamais une division par zéro, jamais un ratio inventé

            # Chantier notation graduée (Partie 3/3) — numérateur = somme
            # des completion_ratio réels (via subquestion_outcomes), jamais
            # le comptage binaire total_successful (qui traiterait un 0.667
            # comme un échec total, cf. diagnostic). total_successful reste
            # calculé ci-dessus pour subquestions_succeeded_count (fait
            # d'audit "pleinement réussies", jamais consommé dans le calcul).
            ratio_sum = sum(
                (_outcome_completion_ratio(o) for c in group for o in c.subquestion_outcomes),
                Decimal("0"),
            )
            performance = _round(
                ratio_sum / Decimal(total_covered), Decimal("0.00001")
            )
            observations.append(SubmissionCompetencyObservation(
                competency=competency,
                performance_copie=performance,
                subquestions_covered_count=total_covered,
                subquestions_succeeded_count=total_successful,
                question_ids=[c.question_id for c in group],
                subquestion_outcomes=[o for c in group for o in c.subquestion_outcomes],
                decision_reasons=[r for c in group for r in c.decision_reasons],
            ))
        return observations

    @staticmethod
    def build_competency_line(
        competency: C2PCTSkillCode,
        observations: list[CompetencyObservationRecord],
        decay_factor: Decimal,
        trend_threshold_percent: Decimal,
        persistent_weakness_threshold: Decimal,
        persistent_weakness_window: int,
        # Chantier notation graduée (Partie 3/3) — défauts alignés sur
        # Settings.COMPETENCY_STRENGTH_RATIO_THRESHOLD/WEAKNESS_RATIO_
        # THRESHOLD, jamais figés en dur ailleurs que cet unique défaut.
        strength_ratio_threshold: Decimal = Decimal("0.8"),
        weakness_ratio_threshold: Decimal = Decimal("0.3"),
    ) -> CompetencyProfileLine:
        """
        Niveau 3 — décroissance exponentielle sur TOUT l'historique fourni
        (poids_i = decay_factor^i, i=0 = observation la plus récente,
        jamais un poids qui tombe complètement à zéro). `observations` est
        re-trié ici par récence décroissante (jamais supposé pré-trié par
        l'appelant, défensif).
        """
        ordered = sorted(observations, key=lambda o: o.created_at, reverse=True)
        n = len(ordered)

        if n == 0:
            # Défensif — ne devrait jamais être appelé sans observation
            # (le service ne construit une ligne que pour une compétence
            # avec au moins une observation). Jamais un niveau inventé.
            return CompetencyProfileLine(
                competency=competency, mastery_level=Decimal("0.00"),
                trend="INSUFFICIENT_DATA", evaluations_count=0,
            )

        # --- Niveau 3 : mastery_level ---
        weights = [decay_factor ** i for i in range(n)]
        weighted_sum = sum(w * o.performance_copie for w, o in zip(weights, ordered))
        weight_total = sum(weights)
        mastery_level = _round((weighted_sum / weight_total) * Decimal("100"))

        # --- trend : <2 observations -> INSUFFICIENT_DATA, jamais deviné.
        # Sinon, fenêtre récente (jusqu'à 3, mais jamais toute l'historique
        # pour garantir une fenêtre "précédente" non vide dès 2 observations)
        # vs fenêtre précédente (jusqu'à 3 suivantes) — dégénère proprement
        # vers "3 vs 3" dès que l'historique est suffisant (>=6).
        if n < 2:
            trend: Literal["IMPROVING", "DECLINING", "STABLE", "INSUFFICIENT_DATA"] = "INSUFFICIENT_DATA"
        else:
            recent_size = min(3, n - 1)
            window_recent = ordered[:recent_size]
            window_previous = ordered[recent_size:recent_size + 3]
            recent_mean = (
                sum(o.performance_copie for o in window_recent) / len(window_recent)
            ) * Decimal("100")
            previous_mean = (
                sum(o.performance_copie for o in window_previous) / len(window_previous)
            ) * Decimal("100")
            diff = recent_mean - previous_mean
            if diff > trend_threshold_percent:
                trend = "IMPROVING"
            elif diff < -trend_threshold_percent:
                trend = "DECLINING"
            else:
                trend = "STABLE"

        confidence_level = _round(min(Decimal("1.0"), Decimal(n) / Decimal("5")))

        # --- is_persistent_weakness : les N plus récentes (window complet
        # requis — historique plus court que la fenêtre ne peut pas encore
        # confirmer une persistance) TOUTES sous le seuil bas.
        window = ordered[:persistent_weakness_window]
        is_persistent_weakness = (
            len(window) == persistent_weakness_window
            and all(o.performance_copie < persistent_weakness_threshold for o in window)
        )

        subquestions_concerned = sorted({
            outcome["subquestion_id"] for obs in ordered for outcome in obs.subquestion_outcomes
        })

        evidence_window = ordered[:min(3, n)]
        evidence_questions: list[uuid.UUID] = []
        seen_questions: set[uuid.UUID] = set()
        for obs in evidence_window:
            for qid in obs.question_ids:
                if qid not in seen_questions:
                    seen_questions.add(qid)
                    evidence_questions.append(qid)

        return CompetencyProfileLine(
            competency=competency,
            mastery_level=mastery_level,
            trend=trend,
            evaluations_count=n,
            subquestions_concerned=subquestions_concerned,
            evidence_questions=evidence_questions,
            identified_difficulties=_rank_difficulties(ordered),
            strengths=_rank_subquestion_pattern(
                ordered, want_success=True,
                strength_threshold=strength_ratio_threshold, weakness_threshold=weakness_ratio_threshold,
            ),
            weaknesses=_rank_subquestion_pattern(
                ordered, want_success=False,
                strength_threshold=strength_ratio_threshold, weakness_threshold=weakness_ratio_threshold,
            ),
            confidence_level=confidence_level,
            is_persistent_weakness=is_persistent_weakness,
        )

    @staticmethod
    def build_report(
        student_id: uuid.UUID,
        module_id: uuid.UUID,
        observations_by_competency: dict[C2PCTSkillCode, list[CompetencyObservationRecord]],
        generated_at: datetime,
        decay_factor: Decimal,
        trend_threshold_percent: Decimal,
        persistent_weakness_threshold: Decimal,
        persistent_weakness_window: int,
        strength_ratio_threshold: Decimal = Decimal("0.8"),
        weakness_ratio_threshold: Decimal = Decimal("0.3"),
    ) -> StudentCompetencyReport:
        """Une ligne par compétence avec AU MOINS une observation — jamais les 7 forcées."""
        lines = [
            CompetencyAssessmentAgent.build_competency_line(
                competency, obs, decay_factor, trend_threshold_percent,
                persistent_weakness_threshold, persistent_weakness_window,
                strength_ratio_threshold, weakness_ratio_threshold,
            )
            for competency, obs in observations_by_competency.items()
            if obs
        ]
        return StudentCompetencyReport(
            student_id=student_id, module_id=module_id, generated_at=generated_at, lines=lines,
        )
