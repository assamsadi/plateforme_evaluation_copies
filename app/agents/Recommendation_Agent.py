"""
Agent — Recommendation_Agent (chantier recommandation, suite au chantier
C2PCT).

Transforme un StudentCompetencyReport (déjà calculé par Competency_
Assessment_Agent, jamais recalculé ici) en une liste d'exercices de la
Library (ARCHIVED_IN_LIBRARY) à recommander à l'étudiant — pure logique de
priorisation déterministe, AUCUN appel LLM, AUCUN accès DB (agent calcule,
RecommendationService assemble les entrées et persiste, même principe
"agent calcule, service persiste" que tous les agents précédents de ce
projet).

Principe de priorisation, en 3 paliers déterministes (jamais un score
opaque unique) :
  1. REMEDIATION prioritaire — CompetencyProfileLine.is_persistent_weakness
     True : toujours devant, peu importe le mastery_level exact (une
     faiblesse persistante prime sur une faiblesse ponctuelle).
  2. REMEDIATION standard — mastery_level sous RECOMMENDATION_WEAK_MASTERY_
     THRESHOLD, mais pas persistante.
  3. VERIFICATION — mastery_level élevé (>= seuil) MAIS confidence_level
     sous RECOMMENDATION_LOW_CONFIDENCE_THRESHOLD (peu d'observations) :
     JAMAIS traité comme acquis, catégorie distincte de REMEDIATION (pour
     que l'étudiant/le prof distinguent "à retravailler" de "à confirmer").
  4. Ni l'un ni l'autre (mastery_level haut ET confidence_level haut) :
     AUCUNE recommandation générée — même philosophie que "jamais les 7
     compétences forcées" déjà appliquée par CompetencyProfileLine.

relevance_score (Decimal 0.0-1.0) dérivé déterministiquement du palier +
de l'écart au seuil dans ce palier — bande [0.667,1.0] palier 1,
[0.333,0.667) palier 2, [0.0,0.333) palier 3 : garantit l'ordre entre
paliers quel que soit l'écart exact, jamais un nombre arbitraire.

reason : texte déterministe assemblé depuis des données déjà connues
(mastery_level, confidence_level, evaluations_count, is_persistent_
weakness) — jamais un texte généré/halluciné, même discipline que
Competency_Assessment_Agent.identified_difficulties.

Sélection des exercices (clôture — matching fin + difficulté) :
1. Fin d'abord — ne garder que les exercices dont covered_subquestions
   recoupe RÉELLEMENT CompetencyProfileLine.weaknesses de cette ligne
   (sous-questions ratées de façon répétée, cf. Competency_Assessment_Agent.
   _rank_subquestion_pattern) : cible le symptôme précis, pas seulement
   "faible en telle compétence" en général.
2. Repli compétence entière — si aucun exercice ne matche au niveau fin
   (bibliothèque trop pauvre pour cette sous-question précise), retomber
   sur TOUTE la compétence (comportement d'origine) plutôt que ne rien
   recommander : une recommandation moins précise mais basée sur du réel
   vaut mieux qu'aucune recommandation.
3. Difficulté ciblée — PRÉFÉRENCE (pas un filtre dur) pour la difficulté
   du palier (cf. _select_difficulty) parmi les candidats retenus aux
   étapes 1-2 ; repli vers toutes difficultés si aucun exercice de la
   Library ne porte la difficulté cible pour cette compétence — même
   philosophie qu'au point 2 : jamais zéro recommandation à cause d'un
   critère de raffinement que la Library ne peut pas satisfaire.
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from app.agents.Competency_Assessment_Agent import CompetencyProfileLine
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode


def _round(value: Decimal, places: Decimal = Decimal("0.001")) -> Decimal:
    return value.quantize(places, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Entrées — assemblées par RecommendationService depuis ExerciseRepository.
# list_library_by_module + c2pct_scaffold.get_competency_for_subquestion,
# jamais recalculées par l'agent (aucun accès DB ici).
# ---------------------------------------------------------------------------

@dataclass
class ExerciseCompetencyCoverage:
    """
    Un exercice de la Library — compétences réellement couvertes,
    sous-questions précises couvertes (matching fin, clôture) et difficulté
    déclarée par le professeur à l'archivage (None si jamais archivé avec
    difficulté — ne devrait pas arriver en pratique, cf. ExerciseService.
    publish, mais l'agent reste défensif : jamais un candidat exclu
    silencieusement pour cette seule raison, cf. repli difficulté ci-dessous).
    """
    exercise_id: uuid.UUID
    exercise_title: str
    competencies: frozenset[C2PCTSkillCode] = field(default_factory=frozenset)
    covered_subquestions: frozenset[str] = field(default_factory=frozenset)
    difficulty_level: str | None = None


# ---------------------------------------------------------------------------
# Sortie
# ---------------------------------------------------------------------------

@dataclass
class ExerciseRecommendation:
    exercise_id: uuid.UUID
    exercise_title: str
    competency: C2PCTSkillCode
    category: str  # "remediation" | "verification"
    reason: str
    relevance_score: Decimal
    # Difficulté RÉELLE de l'exercice retenu (peut différer de la difficulté
    # CIBLE du palier si la Library n'avait rien à la difficulté cible pour
    # cette compétence, cf. repli — jamais None si l'exercice a bien une
    # difficulty_level déclarée, cf. ExerciseCompetencyCoverage).
    difficulty_level: str | None = None


@dataclass
class StudentRecommendationSet:
    student_id: uuid.UUID
    module_id: uuid.UUID
    generated_at: datetime
    recommendations: list[ExerciseRecommendation] = field(default_factory=list)


class RecommendationAgent:
    """Calcul déterministe pur — aucun appel LLM, aucun accès DB."""

    AGENT_NAME = "Recommendation_Agent"

    @staticmethod
    def _priority_tier(
        line: CompetencyProfileLine,
        weak_mastery_threshold: Decimal,
        low_confidence_threshold: Decimal,
    ) -> tuple[int, str, Decimal] | None:
        """
        Retourne (tier 1-3, category, gap_within_tier 0.0-1.0) ou None si
        aucune recommandation ne s'applique à cette ligne (mastery haut ET
        confiance haute — rien à recommander, jamais forcé).
        """
        if line.is_persistent_weakness:
            gap = Decimal("1.0")
            if weak_mastery_threshold > 0:
                gap = min(
                    Decimal("1.0"),
                    max(Decimal("0.0"), (weak_mastery_threshold - line.mastery_level) / weak_mastery_threshold),
                )
            return 3, "remediation", gap

        if line.mastery_level < weak_mastery_threshold:
            gap = min(
                Decimal("1.0"),
                max(Decimal("0.0"), (weak_mastery_threshold - line.mastery_level) / weak_mastery_threshold),
            )
            return 2, "remediation", gap

        if line.confidence_level < low_confidence_threshold:
            gap = Decimal("1.0")
            if low_confidence_threshold > 0:
                gap = min(
                    Decimal("1.0"),
                    max(Decimal("0.0"), (low_confidence_threshold - line.confidence_level) / low_confidence_threshold),
                )
            return 1, "verification", gap

        return None

    # Difficulté CIBLE par palier (clôture — préférence, jamais un filtre
    # dur, cf. docstring module) : tier 3 (faiblesse persistante) -> FACILE
    # pour reconstruire les bases ; tier 2 (faiblesse ponctuelle) ->
    # INTERMEDIAIRE ; tier 1 (VERIFICATION, mastery haut/confiance basse) ->
    # AVANCE pour stress-tester une maîtrise pas encore confirmée, jamais
    # remédier à quelque chose qui n'est pas cassé.
    _DIFFICULTY_BY_TIER = {3: "facile", 2: "intermediaire", 1: "avance"}

    @staticmethod
    def _select_difficulty(tier: int) -> str:
        return RecommendationAgent._DIFFICULTY_BY_TIER[tier]

    @staticmethod
    def _weak_subquestion_ids(line: CompetencyProfileLine) -> frozenset[str]:
        """
        line.weaknesses porte des libellés formatés "{id} ({label})" (cf.
        Competency_Assessment_Agent._rank_subquestion_pattern) — jamais
        l'id brut directement. Reconstruit l'ensemble des ids bruts pour le
        matching fin, jamais une comparaison de texte formaté.
        """
        return frozenset(w.split(" (", 1)[0] for w in line.weaknesses)

    @staticmethod
    def _build_reason(line: CompetencyProfileLine, category: str, difficulty: str) -> str:
        """Texte déterministe — uniquement des valeurs déjà calculées par CompetencyProfileLine, jamais généré."""
        competency_label = line.competency.value
        if line.is_persistent_weakness:
            return (
                f"Faiblesse persistante en {competency_label} "
                f"(maîtrise {line.mastery_level}%, {line.evaluations_count} évaluation(s)) — "
                f"priorité de remédiation, exercice de niveau {difficulty}."
            )
        if category == "remediation":
            return (
                f"Maîtrise sous le seuil en {competency_label} ({line.mastery_level}%) — "
                f"exercice de remédiation recommandé, niveau {difficulty}."
            )
        return (
            f"Maîtrise élevée en {competency_label} ({line.mastery_level}%) mais seulement "
            f"{line.evaluations_count} évaluation(s) (confiance {line.confidence_level}) — "
            f"exercice de vérification recommandé, niveau {difficulty}, jamais traité comme acquis."
        )

    @staticmethod
    def generate(
        student_id: uuid.UUID,
        module_id: uuid.UUID,
        competency_lines: list[CompetencyProfileLine],
        library_coverage: list[ExerciseCompetencyCoverage],
        generated_at: datetime,
        weak_mastery_threshold: Decimal,
        low_confidence_threshold: Decimal,
        max_per_competency: int,
        max_total: int,
    ) -> StudentRecommendationSet:
        recommendations: list[ExerciseRecommendation] = []

        for line in competency_lines:
            tier_info = RecommendationAgent._priority_tier(
                line, weak_mastery_threshold, low_confidence_threshold,
            )
            if tier_info is None:
                continue
            tier, category, gap = tier_info

            # Bande [0,1] par palier — garantit tier 3 (persistant) > tier 2
            # (faiblesse ponctuelle) > tier 1 (vérification) quel que soit
            # l'écart exact dans chaque palier (cf. docstring module).
            relevance_score = _round(
                (Decimal(tier - 1) + gap) / Decimal(3)
            )
            target_difficulty = RecommendationAgent._select_difficulty(tier)

            # Étape 1/2 — fin (weaknesses), repli compétence entière (cf.
            # docstring module, point "Sélection des exercices").
            competency_candidates = [
                cov for cov in library_coverage if line.competency in cov.competencies
            ]
            weak_ids = RecommendationAgent._weak_subquestion_ids(line)
            fine_candidates = [
                cov for cov in competency_candidates if cov.covered_subquestions & weak_ids
            ]
            candidates = fine_candidates if fine_candidates else competency_candidates

            # Étape 3 — préférence de difficulté, repli si la Library n'a
            # rien à la difficulté cible pour cette compétence.
            difficulty_matched = [
                cov for cov in candidates if cov.difficulty_level == target_difficulty
            ]
            final_candidates = difficulty_matched if difficulty_matched else candidates

            for cov in final_candidates[:max_per_competency]:
                reason = RecommendationAgent._build_reason(
                    line, category, cov.difficulty_level or target_difficulty,
                )
                recommendations.append(ExerciseRecommendation(
                    exercise_id=cov.exercise_id,
                    exercise_title=cov.exercise_title,
                    competency=line.competency,
                    category=category,
                    reason=reason,
                    relevance_score=relevance_score,
                    difficulty_level=cov.difficulty_level,
                ))

        recommendations.sort(key=lambda r: r.relevance_score, reverse=True)
        recommendations = recommendations[:max_total]

        return StudentRecommendationSet(
            student_id=student_id, module_id=module_id,
            generated_at=generated_at, recommendations=recommendations,
        )
