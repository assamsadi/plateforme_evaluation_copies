"""
Service EventPublisher — point d'entrée UNIQUE pour publier un événement
métier sur Kafka depuis les autres services (§ description du dossier :
"publication Kafka depuis les autres services").

Pourquoi une couche au-dessus de app.core.kafka_client.publish_event() :
1. Validation du payload par le schema Pydantic dédié (event_schemas.py)
   AVANT publication — un service appelant ne doit jamais pouvoir publier
   un payload malformé sur un topic (kafka_client.publish_event() est
   volontairement générique/non typé, la validation est de la
   responsabilité de l'appelant, donc ici).
2. Un event_id (UUID) unique généré à CET endroit, jamais par
   l'appelant : c'est la garantie d'idempotence côté consumer
   (ProcessedEvent) qui en dépend, autant centraliser sa génération.
3. Une méthode par topic (plutôt qu'une méthode générique
   publish(topic, payload)) : la signature typée de chaque méthode rend
   impossible d'envoyer les mauvais champs sur le mauvais topic — erreur
   qui ne serait sinon détectée qu'à l'exécution par Pydantic.

Ne fait AUCUN accès DB : ce service est un pur passe-plat vers Kafka. Les
services appelants restent responsables de leur propre transaction ; la
publication a lieu APRÈS le commit de la transaction métier (sans quoi un
rollback laisserait un événement publié orphelin, sans contrepartie en
DB) — c'est à l'appelant de respecter cet ordre, pas à ce service de le
deviner.

publish_notification_best_effort() (Kafka en notification pure, décision
actée — jamais un déclencheur du pipeline) : introduit après avoir constaté
qu'aucun appelant n'enveloppait un appel EventPublisherService dans un
try/except (tout comme kafka_client.publish_event() lui-même) ; un broker
indisponible faisait donc échouer le nœud LangGraph appelant. Sites déjà
couverts : evaluation_node.py, recommendation_node.py. TODO sur
publish_feedback_recorded ci-dessous pour le prochain site —
feedback_generation_node.py, pas encore construit) — jamais dupliqué en
ligne à chaque site.

Cas à part, publish_extraction_ready : l'appel a été RETIRÉ de
submission_ocr_pipeline_service.py (2026-08-30), pas enveloppé — aucun
consumer n'existe pour EXTRACTION_READY (vérifié par grep), et l'enveloppe
best-effort payait quand même ~4s de timeout de connexion PAR bloc rattaché
(boucle sur attached_blocks), ralentissant le nœud de plusieurs minutes sur
un document à nombreux blocs pour un événement que personne ne lit. Un futur
consumer réel réintroduirait cet appel via publish_notification_best_effort,
jamais un appel bloquant nu.
"""
import logging
import uuid
from typing import Coroutine, Protocol

from app.core.kafka_client import KafkaTopic, publish_event
from app.domain.schemas.event_schemas import (
    ArbitrationRequiredPayload,
    CorrectionTriagedPayload,
    EvaluationCompletedPayload,
    ExerciseArchivedToLibraryPayload,
    ExerciseCreatedPayload,
    ExercisePublishedPayload,
    ExtractionReadyPayload,
    FeedbackRecordedPayload,
    JobFailedPayload,
    JobResumedPayload,
    NotebookLMEnrichmentCompletedPayload,
    RecommendationGeneratedPayload,
    SubmissionCreatedPayload,
    VariantsReadyPayload,
)

logger = logging.getLogger(__name__)


async def publish_notification_best_effort(publish_call: Coroutine[None, None, str]) -> None:
    """
    Enveloppe n'importe quel appel EventPublisherService.publish_*(...) —
    log l'échec (broker indisponible, timeout, etc.), ne le propage JAMAIS :
    Kafka est un mécanisme de notification pure ici, pas un déclencheur du
    pipeline synchrone LangGraph (décision actée). Usage :
        await publish_notification_best_effort(events.publish_evaluation_completed(payload))
    """
    try:
        await publish_call
    except Exception:
        logger.exception(
            "Échec de publication d'un événement Kafka (notification pure) — "
            "pipeline non bloqué, poursuite normale."
        )


class EventPublisherServiceProtocol(Protocol):
    async def publish_exercise_created(self, payload: ExerciseCreatedPayload) -> str: ...
    async def publish_exercise_published(self, payload: ExercisePublishedPayload) -> str: ...
    async def publish_exercise_archived_to_library(
        self, payload: ExerciseArchivedToLibraryPayload
    ) -> str: ...
    async def publish_submission_created(self, payload: SubmissionCreatedPayload) -> str: ...
    async def publish_extraction_ready(self, payload: ExtractionReadyPayload) -> str: ...
    async def publish_variants_ready(self, payload: VariantsReadyPayload) -> str: ...
    async def publish_correction_triaged(self, payload: CorrectionTriagedPayload) -> str: ...
    async def publish_arbitration_required(self, payload: ArbitrationRequiredPayload) -> str: ...
    async def publish_evaluation_completed(self, payload: EvaluationCompletedPayload) -> str: ...
    async def publish_feedback_recorded(self, payload: FeedbackRecordedPayload) -> str: ...
    async def publish_recommendation_generated(self, payload: RecommendationGeneratedPayload) -> str: ...
    async def publish_notebooklm_enrichment_completed(
        self, payload: NotebookLMEnrichmentCompletedPayload
    ) -> str: ...
    async def publish_job_failed(self, payload: JobFailedPayload) -> str: ...
    async def publish_job_resumed(self, payload: JobResumedPayload) -> str: ...


class EventPublisherService:
    async def _publish(self, topic: KafkaTopic, payload) -> str:
        event_id = str(uuid.uuid4())
        await publish_event(topic, event_id, payload.model_dump(mode="json"))
        return event_id

    async def publish_exercise_created(self, payload: ExerciseCreatedPayload) -> str:
        return await self._publish(KafkaTopic.EXERCISE_CREATED, payload)

    async def publish_exercise_published(self, payload: ExercisePublishedPayload) -> str:
        return await self._publish(KafkaTopic.EXERCISE_PUBLISHED, payload)

    async def publish_exercise_archived_to_library(
        self, payload: ExerciseArchivedToLibraryPayload
    ) -> str:
        return await self._publish(KafkaTopic.EXERCISE_ARCHIVED_TO_LIBRARY, payload)

    async def publish_submission_created(self, payload: SubmissionCreatedPayload) -> str:
        return await self._publish(KafkaTopic.SUBMISSION_CREATED, payload)

    async def publish_extraction_ready(self, payload: ExtractionReadyPayload) -> str:
        return await self._publish(KafkaTopic.EXTRACTION_READY, payload)

    async def publish_variants_ready(self, payload: VariantsReadyPayload) -> str:
        return await self._publish(KafkaTopic.VARIANTS_READY, payload)

    async def publish_correction_triaged(self, payload: CorrectionTriagedPayload) -> str:
        return await self._publish(KafkaTopic.CORRECTION_TRIAGED, payload)

    async def publish_arbitration_required(self, payload: ArbitrationRequiredPayload) -> str:
        return await self._publish(KafkaTopic.ARBITRATION_REQUIRED, payload)

    async def publish_evaluation_completed(self, payload: EvaluationCompletedPayload) -> str:
        return await self._publish(KafkaTopic.EVALUATION_COMPLETED, payload)

    async def publish_feedback_recorded(self, payload: FeedbackRecordedPayload) -> str:
        # TODO(Feedback_Agent, pas encore construit — feedback_agent.py/
        # feedback_generation_node.py font 0 octet, non câblés dans
        # pipeline_graph.py) : appeler ceci en TOUTE FIN de ce nœud une fois
        # construit, via publish_notification_best_effort (même pattern
        # non-bloquant que evaluation_node.py pour publish_evaluation_
        # completed — jamais un try/except dupliqué en ligne, jamais un
        # appel qui bloquerait le pipeline si Kafka est indisponible).
        return await self._publish(KafkaTopic.FEEDBACK_RECORDED, payload)

    async def publish_recommendation_generated(self, payload: RecommendationGeneratedPayload) -> str:
        return await self._publish(KafkaTopic.RECOMMENDATION_GENERATED, payload)

    async def publish_notebooklm_enrichment_completed(
        self, payload: NotebookLMEnrichmentCompletedPayload
    ) -> str:
        return await self._publish(KafkaTopic.NOTEBOOKLM_ENRICHMENT_COMPLETED, payload)

    async def publish_job_failed(self, payload: JobFailedPayload) -> str:
        return await self._publish(KafkaTopic.JOB_FAILED, payload)

    async def publish_job_resumed(self, payload: JobResumedPayload) -> str:
        return await self._publish(KafkaTopic.JOB_RESUMED, payload)