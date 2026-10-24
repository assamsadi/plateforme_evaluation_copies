"""
Configuration Celery : instance partagée de l'app, définition des queues,
politique de retry par défaut.

Importé par :
- l'API (pour dispatcher des tâches, ex. .delay()/.apply_async())
- le worker (worker_main.py, pour exécuter les tâches)

Les queues sont volontairement séparées par nature de traitement, pour
permettre de déployer des workers Celery distincts par queue (concurrence
et priorité différentes selon la charge réelle de chaque type de tâche) :
    celery -A app.core.broker worker -Q ocr --concurrency=2
    celery -A app.core.broker worker -Q llm --concurrency=4
    celery -A app.core.broker worker -Q notifications --concurrency=8
    celery -A app.core.broker worker -Q maintenance --concurrency=1
(Ces flags de déploiement sont définis dans docker-compose.yml, pas ici.)
"""
from enum import StrEnum

from celery import Celery
from kombu import Queue

from app.core.config import settings


class CeleryQueue(StrEnum):
    """
    Noms de queues centralisés — à utiliser partout ailleurs dans le code
    (ex. @celery_app.task(queue=CeleryQueue.OCR)) plutôt que des strings
    en dur, pour éviter les fautes de frappe silencieuses.
    """
    OCR = "ocr"                    # ocr_teacher_correction, ocr_student
    LLM = "llm"                    # variant_generation, comparison, evaluation,
                                    # c2pct_detection, feedback_generation,
                                    # recommendation, vlm_verification_agent
    NOTIFICATIONS = "notifications"  # notifications étudiant/prof
    MAINTENANCE = "maintenance"    # archivage deadline, fine-tuning périodique


# Politique de retry par défaut, à réutiliser dans la définition de chaque
# tâche via : @celery_app.task(bind=True, autoretry_for=(Exception,), **DEFAULT_RETRY_POLICY)
DEFAULT_RETRY_POLICY: dict = {
    "retry_backoff": True,       # backoff exponentiel entre chaque tentative
    "retry_backoff_max": 600,    # plafond du backoff : 10 minutes
    "retry_jitter": True,        # ajoute un aléa pour éviter les retries synchronisés
    "max_retries": 5,
}


celery_app = Celery(
    settings.APP_NAME,
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    # Sans `include`, un worker démarré avec `-A app.core.broker` (ou via
    # worker_main.py, qui se contente d'importer celery_app) n'a jamais
    # connaissance des tâches définies dans app/tasks/*.py : elles ne sont
    # enregistrées dans le process API que parce que les services les
    # importent directement pour appeler .delay(). Constaté en pratique :
    # "Received unregistered task ... Did you remember to import the
    # module containing this task?" pour CHAQUE tâche, systématiquement,
    # sur un worker fraîchement démarré.
    include=[
        "app.tasks.arbitration_tasks",
        "app.tasks.contestation_tasks",
        "app.tasks.exercise_tasks",
        "app.tasks.job_tasks",
        "app.tasks.notebooklm_tasks",
        "app.tasks.solution_variant_generation_tasks",
        "app.tasks.submission_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Un ack après exécution complète (pas avant) : si le worker crashe
    # en plein milieu, la tâche est reprise par un autre worker plutôt
    # que perdue silencieusement. Cohérent avec l'exigence d'idempotence
    # (§7 du résumé d'architecture).
    task_acks_late=True,
    task_reject_on_worker_lost=True,

    # Un worker traite une tâche à la fois avant d'en prendre une nouvelle :
    # évite qu'un worker accapare plusieurs tâches longues (OCR/LLM) et en
    # affame d'autres en attente.
    worker_prefetch_multiplier=1,

    task_default_queue=CeleryQueue.LLM,
    task_queues=(
        Queue(CeleryQueue.OCR),
        Queue(CeleryQueue.LLM),
        Queue(CeleryQueue.NOTIFICATIONS),
        Queue(CeleryQueue.MAINTENANCE),
    ),
)