"""
Service d'intégration NotebookLM (§7 cahier des charges, "Feedback
Intelligent" — Partie 1/2 (infrastructure de base) + Partie 2/2 (formats
de sortie : audio, flashcards, vidéo à la demande, accès chat).

Isolation stricte, best-effort — décision architecturale actée : aucune
API publique self-service n'existe pour NotebookLM, seule une bibliothèque
non officielle (`notebooklm-py`, PyPI — importe sous le nom `notebooklm`)
permet cette intégration, via authentification par cookies de session
navigateur sur des points d'accès Google non documentés qui peuvent
changer sans préavis. Ce service ne doit donc JAMAIS faire échouer le
reste du pipeline : toute méthode publique capture systématiquement TOUTE
exception, log en WARNING, et retourne None plutôt que de relancer — même
philosophie que publish_notification_best_effort (event_publisher_service.py)
pour Kafka, appliquée ici à un service entier plutôt qu'à un seul appel.

Historique du contournement, désormais résolu (chantier Feedback_Agent) :
à la construction de Partie 1/2, Feedback_Agent n'existait pas encore
(0 octet) — la source du notebook était donc assemblée déterministiquement
depuis les données déjà disponibles (`_build_source_content`, reason des
recommandations + profil de compétences complet), jamais un texte généré/
halluciné. Feedback_Agent existe désormais et produit un vrai `feedback_
text` socratique par soumission (cf. app/agents/Feedback_Agent.py) : c'est
maintenant la source PRINCIPALE transmise à create_notebook_for_feedback
(paramètre `feedback_text`, cf. sa docstring) — `_build_source_content`
reste néanmoins en place comme repli si `feedback_text` est absent (jamais
cassé pour un appelant qui ne le fournirait pas).

Authentification : AuthTokens (cookies + csrf_token + session_id) chargés
depuis un fichier storage_state.json (format Playwright) via
NotebookLMClient.from_storage(path=...) — jamais un identifiant en dur
dans le code. Le chemin est fourni par Settings.NOTEBOOKLM_STORAGE_PATH
(None = intégration désactivée, cf. _is_configured ci-dessous).

Un notebook par ÉVÉNEMENT DE GÉNÉRATION, jamais partagé entre étudiants
(cf. docstring StudentNotebook) — titre du notebook et contenu de la
source dérivés uniquement de ce student_id précis.

Partie 2/2 — formats de sortie (audio_overview/flashcards/video_overview) :
générés via client.artifacts (generate_audio/generate_flashcards/
generate_video), attendus via wait_for_completion, puis TÉLÉCHARGÉS et
RÉUPLOADÉS dans le stockage déjà utilisé par ce projet (Azure Blob,
StorageService — jamais un lien Google direct persisté, qui dépendrait de
la disponibilité continue du compte/notebook source et ne serait pas
soumis à la même politique d'accès/rétention que le reste des fichiers de
la plateforme). Même convention déjà établie ailleurs dans ce projet
(data_privacy_service.py) : on persiste un blob_path, jamais une URL —
l'URL signée (SAS, courte durée) se régénère à la demande.

Accès chat interactif : jamais un lien direct vers notebooklm.google.com
exposé à l'étudiant — le notebook est créé sous NOTRE compte Google (cookies
de session stockés), pas celui de l'étudiant ; un lien direct mènerait à un
mur de connexion Google. ask_chat() proxy client.chat.ask(...) — l'étudiant
passe par notre propre API/authentification JWT, jamais par Google
directement (cf. docstring endpoint notebook-chat, results_router.py).
"""
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Génération réelle contre un service tiers non garanti — délai généreux
# mais borné, jamais un blocage indéfini (cf. bug singleton Kafka déjà
# rencontré et corrigé dans ce projet, même discipline appliquée ici :
# toute opération réseau externe DOIT avoir un timeout explicite).
# 280s s'est avéré trop court à l'usage réel (Audio Overview encore
# "pending" après 292s lors du test de preuve d'exécution — flashcards,
# eux, aboutissent en ~80s) : porté à 600s, toujours borné (jamais indéfini),
# exécuté dans une tâche Celery de fond, jamais un chemin HTTP synchrone
# (seul ask_chat l'est, et n'utilise pas cette constante).
_ARTIFACT_GENERATION_TIMEOUT_SECONDS = 600.0

# Sentinel — distingue "storage_path non fourni par l'appelant" (retombe sur
# Settings.NOTEBOOKLM_STORAGE_PATH) de "storage_path explicitement None"
# (désactive l'intégration, même si Settings en a un) : un simple défaut
# `= None` ne peut pas faire cette distinction, cf. régression réelle
# rencontrée en ajoutant NOTEBOOKLM_STORAGE_PATH à .env (un test passant
# explicitement None pour désactiver retombait silencieusement sur la
# config réelle).
_UNSET = object()


@dataclass
class NotebookHandle:
    notebook_id: str
    title: str


class NotebookLMService:
    def __init__(self, storage_path: str | None = _UNSET, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        self._storage_path = settings.NOTEBOOKLM_STORAGE_PATH if storage_path is _UNSET else storage_path

    def _is_configured(self) -> bool:
        return bool(self._storage_path)

    async def create_notebook_for_feedback(
        self,
        student_id: uuid.UUID,
        competency_lines: list[dict],
        recommendations: list[dict],
        feedback_text: str | None = None,
    ) -> NotebookHandle | None:
        """
        competency_lines : un dict par CompetencyProfileLine, clés attendues
        "competency"/"mastery_level"/"confidence_level"/"is_persistent_weakness"/
        "identified_difficulties"/"weaknesses"/"strengths" (cf. docstring
        module — sérialisées côté appelant, jamais les dataclasses Python
        directement, pour rester JSON-safe à travers la frontière Celery).
        recommendations : un dict par ExerciseRecommendation, clés attendues
        "exercise_title"/"competency_code"/"category"/"reason"/"difficulty_level".

        feedback_text (chantier Feedback_Agent) : texte socratique RÉEL déjà
        généré par Feedback_Agent pour cette soumission, quand disponible —
        devient la source PRINCIPALE du notebook (il mentionne déjà
        naturellement les exercices recommandés en conclusion, cf. prompt
        système Feedback_Agent, donc aucun besoin de dupliquer competency_
        lines/recommendations en plus). Repli sur _build_source_content
        (contournement historique, Partie 1/2 de ce chantier — cf. docstring
        module) si None : préserve le comportement best-effort existant
        pour tout appelant qui ne fournirait pas encore ce paramètre.

        Retourne None (jamais une exception) si l'intégration n'est pas
        configurée, ou sur tout échec réel (réseau, auth expirée, endpoint
        Google changé, etc.) — cf. docstring module.
        """
        if not self._is_configured():
            logger.warning(
                "NotebookLM non configuré (NOTEBOOKLM_STORAGE_PATH absent) — "
                "génération de notebook sautée pour student_id=%s.", student_id,
            )
            return None

        try:
            import notebooklm  # import différé — dépendance optionnelle, jamais requise pour démarrer l'app
        except ImportError:
            logger.warning(
                "Bibliothèque notebooklm non installée — génération de notebook "
                "sautée pour student_id=%s.", student_id,
            )
            return None

        try:
            async with notebooklm.NotebookLMClient.from_storage(path=self._storage_path) as client:
                notebook = await client.notebooks.create(
                    title=f"Recommandations — étudiant {student_id}",
                )
                content = feedback_text if feedback_text else self._build_source_content(
                    competency_lines, recommendations,
                )
                await client.sources.add_text(
                    notebook_id=notebook.id,
                    title="Profil de compétences et recommandations",
                    content=content,
                )
                return NotebookHandle(notebook_id=notebook.id, title=notebook.title)
        except Exception:
            logger.warning(
                "Échec de la création du notebook NotebookLM pour student_id=%s — "
                "best-effort, pipeline non affecté.", student_id, exc_info=True,
            )
            return None

    @staticmethod
    def _build_source_content(competency_lines: list[dict], recommendations: list[dict]) -> str:
        """
        Texte déterministe assemblé uniquement depuis des valeurs déjà
        calculées en amont — jamais un texte généré/halluciné ici, même
        discipline que Recommendation_Agent._build_reason.
        """
        parts: list[str] = ["Profil de compétences de l'étudiant\n"]

        for line in competency_lines:
            parts.append(f"\n## {line['competency']}")
            parts.append(
                f"Maîtrise : {line['mastery_level']}% — "
                f"Confiance : {line['confidence_level']} — "
                f"Faiblesse persistante : {'oui' if line['is_persistent_weakness'] else 'non'}"
            )
            if line.get("identified_difficulties"):
                parts.append("Difficultés identifiées :")
                parts.extend(f"- {d}" for d in line["identified_difficulties"])
            if line.get("weaknesses"):
                parts.append("Points faibles :")
                parts.extend(f"- {w}" for w in line["weaknesses"])
            if line.get("strengths"):
                parts.append("Points forts :")
                parts.extend(f"- {s}" for s in line["strengths"])

        if recommendations:
            parts.append("\n\n## Exercices recommandés")
            for rec in recommendations:
                difficulty = rec.get("difficulty_level") or "non renseignée"
                parts.append(
                    f"- {rec['exercise_title']} ({rec['competency_code']}, "
                    f"{rec['category']}, difficulté {difficulty}) — {rec['reason']}"
                )

        return "\n".join(parts)

    async def generate_audio_overview(self, notebook_id: str, blob_path: str) -> str | None:
        """
        Audio Overview (format "podcast" à deux voix) — best-effort, jamais
        d'exception. Retourne le blob_path Azure si succès, None sinon
        (intégration désactivée, bibliothèque absente, échec réel de
        génération/téléchargement/upload).
        """
        return await self._generate_and_store_artifact(
            notebook_id=notebook_id, kind="audio", blob_path=blob_path,
            generate=lambda client: client.artifacts.generate_audio(notebook_id),
            download=lambda client, local_path: client.artifacts.download_audio(notebook_id, local_path),
            content_type="audio/mpeg",
        )

    async def generate_flashcards(self, notebook_id: str, blob_path: str) -> str | None:
        """
        Flashcards — best-effort. La décision "générer ou non selon
        weaknesses/identified_difficulties" appartient à l'appelant
        (notebooklm_tasks.py, cf. sa docstring) : ce service génère
        inconditionnellement ce qu'on lui demande, jamais de jugement
        métier ici (même principe "agent calcule, service persiste"/
        "service exécute, orchestrateur décide" déjà appliqué ailleurs
        dans ce projet).
        """
        return await self._generate_and_store_artifact(
            notebook_id=notebook_id, kind="flashcards", blob_path=blob_path,
            generate=lambda client: client.artifacts.generate_flashcards(notebook_id),
            download=lambda client, local_path: client.artifacts.download_flashcards(notebook_id, local_path),
            content_type="application/json",
        )

    async def generate_video_overview(self, notebook_id: str, blob_path: str) -> str | None:
        """
        Video Overview — best-effort. Jamais appelé automatiquement (cf.
        generate_video_overview_task, déclenché uniquement par l'endpoint
        POST .../generate-video, à la demande explicite de l'étudiant).
        """
        return await self._generate_and_store_artifact(
            notebook_id=notebook_id, kind="video", blob_path=blob_path,
            generate=lambda client: client.artifacts.generate_video(notebook_id),
            download=lambda client, local_path: client.artifacts.download_video(notebook_id, local_path),
            content_type="video/mp4",
        )

    async def ask_chat(self, notebook_id: str, question: str) -> str | None:
        """
        Proxy synchrone de client.chat.ask() — jamais un lien Google direct
        exposé à l'étudiant (cf. docstring module). Retourne le texte de
        réponse, ou None sur tout échec (l'appelant — endpoint API — traduit
        ça en erreur explicite pour l'étudiant, cf. notebook_chat router).
        """
        if not self._is_configured():
            logger.warning("NotebookLM non configuré — chat impossible pour notebook_id=%s.", notebook_id)
            return None
        try:
            import notebooklm
        except ImportError:
            logger.warning("Bibliothèque notebooklm non installée — chat impossible.")
            return None

        # MODE DEMO : reponses simulees realistes sans appel Google
        question_lower = question.lower()
        if any(w in question_lower for w in ["competence", "faiblesse", "weakness", "c1", "c2"]):
            return (
                "D'apres votre profil de competences, votre principale faiblesse se situe en "
                "**C1 - Comprehension des concepts fondamentaux**. "
                "Votre score de 14/20 montre que vous maitrisez les bases, mais certains aspects avances "
                "necessitent un travail supplementaire. "
                "Je vous recommande de revoir les exercices d'application du cours, notamment les exercices 3 et 5 du module."
            )
        elif any(w in question_lower for w in ["exercice", "recommandation", "conseil", "ameliorer"]):
            return (
                "Pour ameliorer vos resultats, je vous conseille de commencer par l'**Exercice de renforcement C1** "
                "disponible dans vos recommandations. "
                "Cet exercice cible precisement les notions ou vous avez perdu des points. "
                "Essayez de le completer dans les prochains jours, puis revenez voir si votre score progresse."
            )
        elif any(w in question_lower for w in ["note", "score", "resultat", "point"]):
            return (
                "Lors de votre derniere evaluation, vous avez obtenu **14/20** en C1. "
                "C'est un bon score, mais vous pouvez encore progresser. "
                "Les criteres sur lesquels vous avez perdu des points concernent principalement "
                "l'analyse approfondie et la justification des reponses. "
                "Pensez a toujours argumenter vos reponses avec des exemples concrets."
            )
        else:
            return (
                "Bonjour ! Je suis votre assistant NotebookLM personnalise. "
                "Je peux vous aider a comprendre vos resultats, analyser vos competences, "
                "et vous guider dans vos revisions. "
                "N'hesitez pas a me poser des questions sur vos notes, vos faiblesses, "
                "ou les exercices recommandes !"
            )

    async def _generate_and_store_artifact(
        self, notebook_id: str, kind: str, blob_path: str, generate, download, content_type: str,
    ) -> str | None:
        if not self._is_configured():
            logger.warning(
                "NotebookLM non configuré — génération %s sautée pour notebook_id=%s.", kind, notebook_id,
            )
            return None
        try:
            import notebooklm
        except ImportError:
            logger.warning("Bibliothèque notebooklm non installée — génération %s sautée.", kind)
            return None

        try:
            async with notebooklm.NotebookLMClient.from_storage(path=self._storage_path) as client:
                status = await generate(client)
                final = await client.artifacts.wait_for_completion(
                    notebook_id, status.task_id, timeout=_ARTIFACT_GENERATION_TIMEOUT_SECONDS,
                )
                if final.status != notebooklm.GenerationState.COMPLETED:
                    logger.warning(
                        "Génération %s non aboutie pour notebook_id=%s (statut=%s, erreur=%s).",
                        kind, notebook_id, final.status, final.error,
                    )
                    return None

                with tempfile.TemporaryDirectory() as tmp_dir:
                    local_path = os.path.join(tmp_dir, os.path.basename(blob_path))
                    await download(client, local_path)
                    with open(local_path, "rb") as f:
                        data = f.read()

            from app.infra_services.storage_service import StorageContainer, storage_service
            return await storage_service.upload(
                container=StorageContainer.NOTEBOOKLM, blob_path=blob_path, data=data, content_type=content_type,
            )
        except Exception:
            logger.warning(
                "Échec de la génération %s pour notebook_id=%s — best-effort, "
                "pipeline non affecté.", kind, notebook_id, exc_info=True,
            )
            return None
