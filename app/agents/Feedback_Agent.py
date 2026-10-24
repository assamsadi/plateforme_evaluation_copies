"""
Feedback_Agent — génère le feedback pédagogique socratique affiché à
l'étudiant après une soumission (§7 cahier des charges, "Feedback
Intelligent" — Feedback_Agent).

SEUL agent de tout le pipeline qui appelle un LLM pour produire du texte
DESTINÉ À L'ÉTUDIANT (Competency_Assessment_Agent et Recommendation_Agent
sont des calculs déterministes purs, aucun appel LLM — cf. leurs
docstrings respectifs). Consomme en LECTURE SEULE le StudentCompetencyReport
déjà calculé par Competency_Assessment_Agent (identified_difficulties/
weaknesses/strengths — extraits RÉELS de la copie de l'étudiant, jamais
réinventés ici) et les recommandations déjà choisies par Recommendation_Agent
— ne modifie ni ne recalcule ni l'un ni l'autre.

Principe socratique (contrainte centrale, non négociable) — cf. le texte
du prompt système ci-dessous : jamais de correction/réponse donnée
directement, toujours une question qui pousse l'étudiant à identifier
lui-même son erreur, TOUJOURS ancrée sur un élément réel fourni (jamais une
question générique déconnectée de la copie). Garde-fou déterministe APRÈS
l'appel LLM (_is_socratic — présence d'au moins un "?") : un texte non
socratique déclenche UN SEUL retry avec rappel explicite dans le prompt ;
au-delà, le texte est quand même utilisé (WARNING loggé, jamais bloquant —
produire un feedback imparfait reste préférable à n'en produire aucun).

Un seul appel LLM par génération (deux au maximum en cas de retry qualité)
— cf. invoke_llm_with_fallback, même signature/pattern que tous les autres
agents LLM de ce projet (messages/response_schema=None/context, retour
4-tuple), cf. Comparative_Evaluation_Agent._call_llm_json comme référence.
Sortie = texte brut en français, jamais du JSON (contrairement aux autres
agents LLM) : rien à parser, le texte EST la sortie utile.
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from app.agents.context import AgentExecutionContext
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.llm.client import invoke_llm_with_fallback
from app.model_registry.models import TaskType

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """Tu es un tuteur pédagogique bienveillant qui rédige un feedback socratique pour
un·e étudiant·e, à partir de son profil de compétences réel sur ce module.

RÈGLE ABSOLUE — principe socratique :
- Tu ne donnes JAMAIS directement la réponse, la correction ou la solution à une erreur.
- Pour chaque difficulté à aborder, pose une question qui pousse l'étudiant·e à
  identifier lui-même/elle-même son erreur, en l'invitant à relire un passage précis
  de sa copie.
- Chaque question ou observation doit s'appuyer sur un élément RÉEL et PRÉCIS fourni
  ci-dessous (un extrait, une sous-question, une compétence précise) — jamais une
  question générique déconnectée de sa copie.

TON :
- Bienveillant et constructif, jamais uniquement négatif.
- Commence par reconnaître au moins une force réelle (strengths fournis) avant
  d'aborder les difficultés.

STRUCTURE ATTENDUE :
1. Une à deux phrases reconnaissant une force réelle de l'étudiant·e.
2. Pour chaque compétence à travailler listée ci-dessous, une ou deux questions
   socratiques ancrées sur les difficultés/faiblesses réelles fournies.
3. Une conclusion qui mentionne naturellement les exercices recommandés fournis
   ci-dessous, comme un prolongement naturel de la réflexion — jamais une liste
   plaquée à la fin.

Exemple de ton attendu (à NE PAS recopier littéralement, juste pour calibrer le style) :
"Relis attentivement ta boucle à la question 3 : à quel moment sais-tu que la
condition d'arrêt doit être vérifiée ? Est-ce que for t'oblige à la préciser dès
le départ, contrairement à while ?"

Réponds UNIQUEMENT avec le texte du feedback en français, prêt à être affiché tel
quel à l'étudiant·e — pas de JSON, pas de balises, pas de préambule du type "Voici
le feedback"."""

_RETRY_REMINDER = (
    "\n\nIMPORTANT : ta réponse précédente ne contenait aucune question et n'était "
    "donc pas socratique. Reformule ENTIÈREMENT ta réponse pour qu'elle contienne au "
    "moins une question qui guide l'étudiant·e à trouver lui-même/elle-même son erreur."
)


@dataclass
class CompetencyFeedbackInput:
    """Une compétence à aborder — toujours issue d'une CompetencyProfileLine réelle, jamais inventée."""
    competency: C2PCTSkillCode
    mastery_level: Decimal
    trend: str
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    identified_difficulties: list[str] = field(default_factory=list)


@dataclass
class RecommendedExerciseInput:
    """Un exercice déjà choisi par Recommendation_Agent — jamais reproposé/reclassé ici."""
    exercise_title: str
    competency: C2PCTSkillCode
    reason: str


@dataclass
class FeedbackReport:
    student_id: uuid.UUID
    submission_id: uuid.UUID
    feedback_text: str  # le texte socratique complet, prêt à être affiché à l'étudiant
    competencies_addressed: list[C2PCTSkillCode]
    generated_at: datetime


class FeedbackAgent:
    """Agent de Feedback Intelligent (§7) — un seul point d'appel LLM, cf. docstring module."""

    AGENT_NAME = "Feedback_Agent"

    async def generate_feedback(
        self,
        student_id: uuid.UUID,
        submission_id: uuid.UUID,
        competencies: list[CompetencyFeedbackInput],
        recommendations: list[RecommendedExerciseInput],
        ctx: AgentExecutionContext,
    ) -> FeedbackReport:
        user_prompt = self._build_user_prompt(competencies, recommendations)
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        feedback_text = await self._call_llm(messages, ctx)

        if not self._is_socratic(feedback_text):
            logger.warning(
                "Feedback non socratique (aucun '?') pour submission_id=%s — retry unique avec rappel explicite.",
                submission_id,
            )
            retry_messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt + _RETRY_REMINDER},
            ]
            feedback_text = await self._call_llm(retry_messages, ctx)
            if not self._is_socratic(feedback_text):
                # Jamais bloquant (cf. docstring module) — un feedback non
                # parfaitement socratique reste préférable à aucun feedback.
                logger.warning(
                    "Feedback toujours non socratique après retry pour submission_id=%s — "
                    "utilisé tel quel (jamais bloquant).", submission_id,
                )

        return FeedbackReport(
            student_id=student_id,
            submission_id=submission_id,
            feedback_text=feedback_text,
            competencies_addressed=[c.competency for c in competencies],
            generated_at=datetime.now(timezone.utc),
        )

    async def _call_llm(self, messages: list[dict], ctx: AgentExecutionContext) -> str:
        """
        Point d'appel LLM unique — vraie signature de invoke_llm_with_fallback
        (messages/response_schema=None/context, retour 4-tuple), même pattern
        que tous les autres agents LLM de ce projet (cf. docstring module).
        Sortie = texte brut, jamais de parsing JSON (contrairement aux autres
        agents : ici le texte EST la sortie utile).

        Bug trouvé sur test réel (2026-08-18, sonde step11) : certains
        clients LangChain (ex. ChatGoogleGenerativeAI) renvoient parfois
        .content sous forme de LISTE de blocs (réponse multi-parties, ex.
        [{"type": "text", "text": "..."}]) plutôt qu'une chaîne — .strip()
        plantait dessus (AttributeError). Reconstruction du texte complet à
        partir des blocs, jamais un texte tronqué au premier bloc.
        """
        result, _spec, _fallback, _tokens = await invoke_llm_with_fallback(
            task_type=TaskType.FEEDBACK_GENERATION,
            messages=messages,
            response_schema=None,
            context=ctx,
        )
        content = result.content if hasattr(result, "content") else result
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        return str(content).strip()

    @staticmethod
    def _is_socratic(text: str) -> bool:
        """Garde-fou déterministe minimal (cf. docstring module) — présence d'au moins un point d'interrogation."""
        return "?" in text

    @staticmethod
    def _build_user_prompt(
        competencies: list[CompetencyFeedbackInput],
        recommendations: list[RecommendedExerciseInput],
    ) -> str:
        sections = ["## Compétences à aborder (profil réel de l'étudiant·e)\n"]
        for c in competencies:
            sections.append(
                f"### Compétence : {c.competency.value}\n"
                f"- Niveau de maîtrise : {c.mastery_level}%\n"
                f"- Tendance : {c.trend}\n"
                f"- Forces réelles : {'; '.join(c.strengths) if c.strengths else 'aucune force spécifique relevée'}\n"
                f"- Faiblesses réelles : {'; '.join(c.weaknesses) if c.weaknesses else 'aucune'}\n"
                f"- Difficultés identifiées (extraits réels de la copie) : "
                f"{'; '.join(c.identified_difficulties) if c.identified_difficulties else 'aucune'}\n"
            )

        sections.append("\n## Exercices déjà recommandés (à mentionner naturellement en conclusion)\n")
        if recommendations:
            for r in recommendations:
                sections.append(f"- « {r.exercise_title} » (compétence : {r.competency.value}) — {r.reason}\n")
        else:
            sections.append("- Aucun exercice recommandé cette fois-ci — ne pas en inventer, conclure sans en mentionner.\n")

        return "".join(sections)
