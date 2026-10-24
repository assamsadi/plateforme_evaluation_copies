"""
StudentNotebook = référence à un notebook NotebookLM créé pour enrichir le
feedback d'une génération de recommandations (§7 cahier des charges,
"Feedback Intelligent" — intégration NotebookLM, Partie 1/2 + Partie 2/2
formats de sortie).

Une ligne PAR ÉVÉNEMENT DE GÉNÉRATION (un run de recommendation_node),
jamais par RecommendedExercise individuelle : un notebook regroupe TOUTES
les recommandations + tout le profil de compétences produits en un seul
passage — mettre notebook_id sur chaque RecommendedExercise dupliquerait
la même référence sur N lignes, et une génération à 0 recommandation
persistée (compétences toutes résolues) n'aurait alors aucune ligne pour
la porter alors qu'un notebook a bien pu être créé (profil de compétences
seul, même sans exercice recommandé). Table séparée, scopée par étudiant
(jamais partagée entre étudiants, cf. NotebookLMService).

notebook_id : identifiant EXTERNE NotebookLM (str, pas un uuid.UUID local)
— format opaque côté fournisseur, jamais réinterprété ici.

Aucune ligne n'est créée en cas d'échec de la CRÉATION du notebook
(intégration best-effort, cf. NotebookLMService — échec loggé en WARNING,
jamais persisté comme état "failed" : rien à réessayer automatiquement).

Partie 2/2 — cette ligne EST modifiée après création (contrairement à
l'hypothèse initiale de la Partie 1) : audio_overview_path/flashcards_path
sont renseignés de façon best-effort par la même tâche Celery une fois le
notebook créé (cf. notebooklm_tasks.py), video_overview_* évolue au fil du
cycle de vie de la génération à la demande (not_requested -> pending ->
ready, ou failed en cas d'échec réel — jamais bloqué sur pending
indéfiniment). *_path stockent des BLOB PATHS Azure (convention déjà
établie par StorageService — jamais une URL directement persistée, qui
expirerait, cf. generate_read_url), None tant que le format correspondant
n'a pas été généré avec succès.

Régénération à la demande (chantier "régénération NotebookLM") —
audio_overview_status/flashcards_status suivent désormais le même cycle de
vie explicite que video_overview_status (GenerationStatus, valeurs
identiques à VideoOverviewStatus + failed) : avant ce chantier, l'audio et
les flashcards n'avaient qu'un chemin nullable (succès best-effort
implicite à la création du notebook, jamais redemandable, jamais d'état
"pending"/"failed" distinguable d'un "pas encore tenté"). Une régénération
réutilise le MÊME blob_path que la génération initiale (StorageService.
upload(overwrite=True) — remplace proprement l'ancien fichier, jamais une
nouvelle version côté stockage) et est bloquée uniquement pendant qu'une
génération est déjà PENDING (dédoublonnage — jamais une deuxième tâche
Celery concurrente pour le même notebook), jamais bloquée depuis READY ou
FAILED (c'est tout l'intérêt de "régénérer").
"""
import uuid
from enum import StrEnum

from sqlalchemy import Enum as PgEnum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class VideoOverviewStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    READY = "ready"
    # Échec réel distinguable d'un "jamais demandé" (avant ce chantier, un
    # échec repliait silencieusement sur NOT_REQUESTED — cf. docstring
    # generate_video_overview_task) — permet au frontend d'afficher une
    # erreur explicite plutôt qu'un état "pas encore demandé" trompeur.
    FAILED = "failed"


class GenerationStatus(StrEnum):
    """
    Cycle de vie générique d'une génération de format de sortie NotebookLM
    (audio/flashcards) — mêmes 4 valeurs que VideoOverviewStatus, type
    Postgres séparé (generation_status) pour ne pas coupler audio/
    flashcards au nom "vidéo" de l'enum historique.
    """
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class StudentNotebook(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "student_notebooks"

    student_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("students.id"), nullable=False, index=True
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("modules.id"), nullable=False
    )
    # Nullable — même principe que RecommendedExercise.submission_id : reste
    # rempli quand une soumission a déclenché la génération, jamais la clé
    # d'accès structurelle.
    submission_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("submissions.id"), nullable=True
    )
    notebook_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # --- Formats de sortie (Partie 2/2) — tous best-effort, tous nullable ---
    audio_overview_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    audio_overview_status: Mapped[GenerationStatus] = mapped_column(
        PgEnum(
            GenerationStatus, name="generation_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=GenerationStatus.NOT_REQUESTED,
    )
    # Jamais généré si weaknesses/identified_difficulties sont vides pour
    # TOUTES les compétences de la génération (cf. docstring tâche Celery —
    # jamais de flashcards vides/génériques) ; une régénération réapplique
    # la même règle contre le profil de compétences ACTUEL (cf.
    # RecommendationService.regenerate_flashcards).
    flashcards_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    flashcards_status: Mapped[GenerationStatus] = mapped_column(
        PgEnum(
            GenerationStatus, name="generation_status", create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=GenerationStatus.NOT_REQUESTED,
    )
    video_overview_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    video_overview_status: Mapped[VideoOverviewStatus] = mapped_column(
        PgEnum(
            VideoOverviewStatus, name="video_overview_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=VideoOverviewStatus.NOT_REQUESTED,
    )



