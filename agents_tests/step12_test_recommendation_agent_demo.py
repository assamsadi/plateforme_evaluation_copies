"""
Démo — Recommendation_Agent (calcul déterministe pur, aucun LLM, aucune DB,
cf. docstring module) : contrairement aux autres agents de ce dossier, il
n'y a rien à interroger en réel (pas de service tiers) — ce script sert
uniquement à VOIR concrètement ce que produit l'agent sur un scénario
réaliste, ce que les tests unitaires (assertions seules) ne montrent pas.

Scénario : un·e étudiant·e avec 4 lignes de profil de compétences
(StudentCompetencyReport, déjà calculé par Competency_Assessment_Agent en
production) couvrant les 4 cas possibles :
  - DATA_AND_PLANNING       : faiblesse PERSISTANTE -> palier 3, remédiation, facile.
  - DECOMPOSITION_AND_ORGANIZATION : faiblesse ponctuelle -> palier 2, remédiation, intermédiaire.
  - ALGORITHMIC_STRUCTURING : maîtrise haute mais peu d'observations -> palier 1, vérification, avancé.
  - SOLUTION_COMMUNICATION  : maîtrise haute ET confiance haute -> AUCUNE recommandation.

Plus une bibliothèque d'exercices avec un cas de repli (aucun exercice ne
couvre la sous-question précise en échec -> repli sur toute la compétence)
pour montrer ce mécanisme aussi, pas seulement le cas nominal.

Lancer depuis la racine du projet :

    .venv/Scripts/python.exe agents_tests/step12_test_recommendation_agent_demo.py
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.agents.Competency_Assessment_Agent import CompetencyProfileLine
from app.agents.Recommendation_Agent import ExerciseCompetencyCoverage, RecommendationAgent
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode

STUDENT_ID = uuid.uuid4()
MODULE_ID = uuid.uuid4()

COMPETENCY_LINES = [
    CompetencyProfileLine(
        competency=C2PCTSkillCode.DATA_AND_PLANNING,
        mastery_level=Decimal("28.0"),
        trend="DECLINING",
        evaluations_count=5,
        confidence_level=Decimal("0.75"),
        is_persistent_weakness=True,
        weaknesses=["1.5 (Identifier les données manquantes, à calculer)"],
        identified_difficulties=["N'a jamais mentionné la contrainte admissible du matériau."],
    ),
    CompetencyProfileLine(
        competency=C2PCTSkillCode.DECOMPOSITION_AND_ORGANIZATION,
        mastery_level=Decimal("45.0"),
        trend="STABLE",
        evaluations_count=3,
        confidence_level=Decimal("0.5"),
        is_persistent_weakness=False,
        weaknesses=["2.2 (Diviser le problème en mini-problèmes)"],
    ),
    CompetencyProfileLine(
        competency=C2PCTSkillCode.ALGORITHMIC_STRUCTURING,
        mastery_level=Decimal("85.0"),
        trend="INSUFFICIENT_DATA",
        evaluations_count=1,
        confidence_level=Decimal("0.2"),
        is_persistent_weakness=False,
    ),
    CompetencyProfileLine(
        competency=C2PCTSkillCode.SOLUTION_COMMUNICATION,
        mastery_level=Decimal("95.0"),
        trend="STABLE",
        evaluations_count=6,
        confidence_level=Decimal("0.9"),
        is_persistent_weakness=False,
    ),
]

LIBRARY_COVERAGE = [
    # Ne couvre PAS 1.5 précisément (la faiblesse réelle) -> déclenche le repli
    # sur toute la compétence DATA_AND_PLANNING plutôt qu'aucune recommandation.
    ExerciseCompetencyCoverage(
        exercise_id=uuid.uuid4(), exercise_title="Identifier les données d'un problème mécanique",
        competencies=frozenset({C2PCTSkillCode.DATA_AND_PLANNING}),
        covered_subquestions=frozenset({"1.1", "1.2"}), difficulty_level="facile",
    ),
    ExerciseCompetencyCoverage(
        exercise_id=uuid.uuid4(), exercise_title="Décomposer un problème de structure en sous-tâches",
        competencies=frozenset({C2PCTSkillCode.DECOMPOSITION_AND_ORGANIZATION}),
        covered_subquestions=frozenset({"2.2"}), difficulty_level="intermediaire",
    ),
    ExerciseCompetencyCoverage(
        exercise_id=uuid.uuid4(), exercise_title="Algorithme de tri avancé",
        competencies=frozenset({C2PCTSkillCode.ALGORITHMIC_STRUCTURING}),
        covered_subquestions=frozenset({"3.1"}), difficulty_level="avance",
    ),
]


def main() -> None:
    result = RecommendationAgent.generate(
        student_id=STUDENT_ID,
        module_id=MODULE_ID,
        competency_lines=COMPETENCY_LINES,
        library_coverage=LIBRARY_COVERAGE,
        generated_at=datetime.now(timezone.utc),
        weak_mastery_threshold=Decimal("60.0"),
        low_confidence_threshold=Decimal("0.6"),
        max_per_competency=2,
        max_total=10,
    )

    print(f"=== Recommendation_Agent : {len(result.recommendations)} recommandation(s) générée(s) ===\n")
    for rec in result.recommendations:
        print(f"[{rec.category}] {rec.competency.value} — relevance_score={rec.relevance_score}")
        print(f"    Exercice : « {rec.exercise_title} » (difficulté : {rec.difficulty_level})")
        print(f"    Raison   : {rec.reason}")
        print()

    addressed = {r.competency for r in result.recommendations}
    exercise_titles = [r.exercise_title for r in result.recommendations]
    fallback_exercise_title = "Identifier les données d'un problème mécanique"
    top_is_persistent_weakness = (
        result.recommendations[0].competency == C2PCTSkillCode.DATA_AND_PLANNING
        if result.recommendations else False
    )

    print("=== Vérifications ===")
    print(f"DATA_AND_PLANNING (persistant) présent, priorité la plus haute : {top_is_persistent_weakness}")
    print(
        "Repli compétence entière observé (exercice ne couvrant pas 1.5 précisément quand même retenu) : "
        f"{fallback_exercise_title in exercise_titles}"
    )
    print(f"SOLUTION_COMMUNICATION (maîtrise+confiance hautes) absent, comme attendu : "
          f"{C2PCTSkillCode.SOLUTION_COMMUNICATION not in addressed}")


if __name__ == "__main__":
    main()
