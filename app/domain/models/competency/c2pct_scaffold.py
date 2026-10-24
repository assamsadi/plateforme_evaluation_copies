"""
C2PCT_SCAFFOLD — les 15 sous-questions officielles de la méthodologie C2PCT
(CHAABI, 2022 — licence CC BY-NC-SA 4.0 : attribution requise, usage non
commercial, partage dans les mêmes conditions ; contenu source reproduit ici
à des fins pédagogiques internes, jamais redistribué commercialement).

Réparties de façon INÉGALE sur les 7 compétences (5 pour DATA_AND_PLANNING,
1 seule pour GENERALIZATION_AND_TRANSFER, etc.) — ce déséquilibre est
délibéré dans le document source, pas une lacune à corriger ici.

PRINCIPE DIRECTEUR (à respecter par tout code consommant ce module, cf.
Extraction_Verification_Agent/Comparative_Evaluation_Agent/Pedagogical_
Evaluation_Agent) : ce module est un DICTIONNAIRE POUR RECONNAÎTRE, jamais
un modèle à imposer. La correction du professeur reste, à chaque étape du
pipeline, la seule autorité sur quelles sous-questions sont réellement
mobilisées pour une question donnée. Si le prof n'en couvre que 2 sur les
15 possibles, c'est 2 — jamais complété artificiellement pour "faire
complet", jamais un total théorique substitué au total réellement couvert.

Aucune détection, aucun matching, aucune logique métier ici — uniquement la
donnée de référence statique et ses accesseurs. Structure figée (dataclass
frozen), pas une table DB : une méthodologie académique stable, comme les 4
ClassicCriterion déjà présents dans evaluation_schemas.py.
"""
from dataclasses import dataclass

from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode


@dataclass(frozen=True)
class C2PCTSubQuestion:
    id: str  # ex. "1.1", "3.2", "4"
    label: str  # description courte de ce que couvre cette sous-question
    reference_prompt: str  # la question exacte posée dans le document CHAABI, pour matching textuel fin


C2PCT_SCAFFOLD: dict[C2PCTSkillCode, list[C2PCTSubQuestion]] = {
    C2PCTSkillCode.DATA_AND_PLANNING: [
        C2PCTSubQuestion(
            id="1.1", label="Lister et catégoriser les données (Problème/Question)",
            reference_prompt="Notez toutes les données citées dans l'énoncé de l'exercice. Puis divisez-les en Données Problème et Données Question.",
        ),
        C2PCTSubQuestion(
            id="1.2", label="Identifier ce qui est demandé et les conditions à respecter",
            reference_prompt="Qu'est-ce qui vous est demandé dans l'exercice ? Quelles sont les conditions à respecter ?",
        ),
        C2PCTSubQuestion(
            id="1.3", label="Déterminer les données nécessaires pour répondre",
            reference_prompt="D'après les informations présentées dans l'exercice, quelles sont les données importantes et nécessaires pour répondre à la question ?",
        ),
        C2PCTSubQuestion(
            id="1.4", label="Représentation du problème (schéma/dessin)",
            reference_prompt="Quelle serait la représentation du problème (Dessin, schéma...) ? Montrez les données importantes et les inconnues.",
        ),
        C2PCTSubQuestion(
            id="1.5", label="Identifier les données manquantes, à calculer",
            reference_prompt="Avez-vous besoin de données supplémentaires qui ne figurent pas dans l'énoncé ? Pourriez-vous les calculer ?",
        ),
    ],
    C2PCTSkillCode.DECOMPOSITION_AND_ORGANIZATION: [
        C2PCTSubQuestion(
            id="2.1", label="Identifier le complément nécessaire (formule/technique/règle)",
            reference_prompt="Avez-vous besoin d'un complément - une formule, une technique, une règle - pour résoudre le problème ?",
        ),
        C2PCTSubQuestion(
            id="2.2", label="Diviser le problème en mini-problèmes",
            reference_prompt="Le problème peut-il être divisé en plusieurs mini-problèmes ? Décrivez-les.",
        ),
    ],
    C2PCTSkillCode.ALGORITHMIC_STRUCTURING: [
        C2PCTSubQuestion(
            id="3.1", label="Décrire les étapes de résolution en mots",
            reference_prompt="Utilisez vos propres mots pour décrire les étapes à suivre pour résoudre le problème.",
        ),
        C2PCTSubQuestion(
            id="3.2", label="Représentation visuelle des étapes (schéma)",
            reference_prompt="Faites une représentation de la solution (Dessin, schéma...) pour décrire les étapes que vous allez suivre.",
        ),
    ],
    C2PCTSkillCode.GENERALIZATION_AND_TRANSFER: [
        C2PCTSubQuestion(
            id="4", label="Identifier un autre problème/contexte réutilisant cette solution",
            reference_prompt="Quel autre type de problème pourriez-vous résoudre avec la solution renseignée ? Pensez à une autre situation/un autre contexte.",
        ),
    ],
    C2PCTSkillCode.SOLUTION_COMMUNICATION: [
        C2PCTSubQuestion(
            id="5", label="Rédiger la réponse finale présentée au professeur",
            reference_prompt="Il est temps de répondre à la question initiale du problème. Écrivez la solution que vous présenterez à votre professeur.",
        ),
    ],
    C2PCTSkillCode.SELF_EVALUATION_AND_CREATIVITY: [
        C2PCTSubQuestion(
            id="6.1", label="Le résultat a-t-il un sens, répond-il à la question posée",
            reference_prompt="Le résultat a-t-il un sens ? Est-ce que vous proposez la réponse à la question ?",
        ),
        C2PCTSubQuestion(
            id="6.2", label="Est-ce la meilleure solution possible, une alternative existe-t-elle",
            reference_prompt="Votre solution est-elle la meilleure ou pourriez-vous en suggérer une autre ?",
        ),
    ],
    C2PCTSkillCode.REFLECTION_AND_METACOGNITION: [
        C2PCTSubQuestion(
            id="7.1", label="Difficultés rencontrées dans la compréhension du problème",
            reference_prompt="Avez-vous eu des difficultés à comprendre ce qui vous était demandé pour ce problème ?",
        ),
        C2PCTSubQuestion(
            id="7.2", label="Utilité de la structure suivie pour résoudre le problème",
            reference_prompt="Avez-vous trouvé utile le fait de suivre cette structure pour résoudre le problème ?",
        ),
    ],
}


def get_all_subquestions() -> list[C2PCTSubQuestion]:
    """Liste à plat des 15 sous-questions, toutes compétences confondues."""
    return [sq for subquestions in C2PCT_SCAFFOLD.values() for sq in subquestions]


def get_subquestions_for(skill: C2PCTSkillCode) -> list[C2PCTSubQuestion]:
    """Sous-questions officielles d'UNE compétence — liste vide si aucune (ne devrait pas arriver, les 7 codes sont couverts)."""
    return C2PCT_SCAFFOLD.get(skill, [])


def find_subquestion_by_id(id: str) -> C2PCTSubQuestion | None:
    """Recherche par id exact (ex. "3.2") — None si absent, jamais une correspondance approximative."""
    for sq in get_all_subquestions():
        if sq.id == id:
            return sq
    return None


def get_competency_for_subquestion(subquestion_id: str) -> C2PCTSkillCode | None:
    """
    Phase 4/4 (Pedagogical_Evaluation_Agent) — compétence PARENTE d'un id de
    sous-question exact, pour regrouper covered_subquestions par compétence.
    None si l'id est inconnu — jamais devinée, jamais une correspondance
    approximative (même garde que find_subquestion_by_id).
    """
    for skill, subquestions in C2PCT_SCAFFOLD.items():
        if any(sq.id == subquestion_id for sq in subquestions):
            return skill
    return None
