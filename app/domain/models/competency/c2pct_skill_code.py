"""
C2PCTSkillCode = catalogue des 7 compétences CHAABI, en enum Python pur
— PAS de table en base (décision actée : le fichier .md, injecté en
contexte complet dans les agents, devient l'unique source de vérité du
contenu des compétences ; cet enum ne sert qu'à typer/valider les
références aux 7 codes dans le reste du code Python/SQL).

Toute évolution du contenu descriptif (nom, description, sous-questions)
se fait dans le fichier .md (ex. app/agents/prompts/c2pct_competencies.md),
pas ici — cet enum ne liste que les 7 codes stables.
"""
from enum import StrEnum


class C2PCTSkillCode(StrEnum):
    DATA_AND_PLANNING = "data_and_planning"                        # 1
    DECOMPOSITION_AND_ORGANIZATION = "decomposition_and_organization"  # 2
    ALGORITHMIC_STRUCTURING = "algorithmic_structuring"             # 3
    GENERALIZATION_AND_TRANSFER = "generalization_and_transfer"     # 4
    SOLUTION_COMMUNICATION = "solution_communication"               # 5
    SELF_EVALUATION_AND_CREATIVITY = "self_evaluation_and_creativity"  # 6
    REFLECTION_AND_METACOGNITION = "reflection_and_metacognition"   # 7