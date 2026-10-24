"""
Configuration centralisée de l'application, chargée depuis les variables
d'environnement (.env en local, App Settings sur Azure en production).
"""
from decimal import Decimal
from functools import lru_cache

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    APP_NAME: str = "plateforme-evaluation-copies"
    ENVIRONMENT: str = Field(default="development")  # development | staging | production
    DEBUG: bool = False

    # --- Base de données (PostgreSQL) ---
    DATABASE_URL: PostgresDsn
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_TIMEOUT_SECONDS: int = 30
    DB_ECHO_SQL: bool = False  # log des requêtes SQL, utile en debug local uniquement

    # --- Broker de tâches (Celery + Redis) ---
    REDIS_URL: RedisDsn
    CELERY_BROKER_URL: RedisDsn | None = None   # si absent, dérivé de REDIS_URL
    CELERY_RESULT_BACKEND: RedisDsn | None = None

    # --- Bus d'événements (Kafka) ---
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"

    # --- Stockage fichiers (Azure Blob Storage) ---
    AZURE_STORAGE_CONNECTION_STRING: str
    AZURE_STORAGE_CONTAINER_SUBMISSIONS: str = "submissions"
    AZURE_STORAGE_CONTAINER_EXERCISES: str = "exercises"
    # Formats de sortie NotebookLM (§7, Partie 2/2) — audio/flashcards/vidéo
    # téléchargés depuis NotebookLM puis réuploadés ici (jamais un lien
    # Google direct persisté, cf. docstring StudentNotebook).
    AZURE_STORAGE_CONTAINER_NOTEBOOKLM: str = "notebooklm-artifacts"

    @field_validator("AZURE_STORAGE_CONNECTION_STRING")
    @classmethod
    def validate_azure_storage_connection_string(cls, v: str) -> str:
        if not v or "AccountName=" not in v or "AccountKey=" not in v:
            raise ValueError(
                "AZURE_STORAGE_CONNECTION_STRING est invalide ou incomplète : "
                "elle doit contenir au minimum 'AccountName=' et 'AccountKey='."
            )
        return v

    # --- Sécurité / JWT ---
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- Authentification "Se connecter avec Google" ---
    # Client ID OAuth 2.0 (Google Cloud Console > APIs & Services >
    # Credentials > OAuth client ID > type "Web application") — sert
    # d'AUDIENCE attendue lors de la vérification du jeton d'identité côté
    # serveur (app/auth/google_oauth.py). None = fonctionnalité désactivée,
    # /auth/login/google refuse alors explicitement plutôt que d'accepter un
    # jeton dont l'audience ne serait jamais vérifiée contre rien.
    GOOGLE_CLIENT_ID: str | None = None

    # --- Observabilité ---
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None
    LOG_LEVEL: str = "INFO"
        # --- Langfuse (LLM Observability) ---
    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_BASE_URL: str = "https://cloud.langfuse.com"

    # --- LLM Providers ---
    GROQ_API_KEY: str | None = None

    # Serveur Ollama local — sans authentification (usage dev/local
    # uniquement, jamais exposé tel quel en production), cf. app/model_
    # registry/providers.py::create_llm_from_spec. Modèles "cloud" Ollama
    # (ex. gemma4:cloud) restent transparents ici : le daemon local proxie
    # lui-même vers ollama.com, notre code parle toujours à localhost.
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # --- Judge0 (bac à sable d'exécution de code, Comparative_Evaluation_Agent
    # mode TEST_CASE_BASED) --- Instance RapidAPI Judge0 CE : pas de conteneur
    # supplémentaire à faire tourner localement (RAM hôte déjà critique, cf.
    # docker-compose.yml), juste une clé RapidAPI gratuite. Absence de clé =
    # JUDGE0_USE_MOCK reste effectivement forcé à True (cf. Judge0SandboxService
    # .__init__ : self.api_url is None -> use_mock=True), jamais un crash au
    # démarrage.
    JUDGE0_API_URL: str = "https://judge0-ce.p.rapidapi.com"
    JUDGE0_API_HOST: str = "judge0-ce.p.rapidapi.com"
    JUDGE0_API_KEY: str | None = None
    JUDGE0_USE_MOCK: bool | None = None  # None = auto (mock si JUDGE0_API_KEY absente)

    # --- Agent & OCR Thresholds ---
    OCR_MIN_LAPLACIAN_VARIANCE: float = 50.0
    OCR_CONFIDENCE_THRESHOLD: float = 0.70
    OCR_MAX_CONCURRENCY: int = 4
    OCR_MAX_RE_READ_ATTEMPTS: int = 1
    DOCUMENT_STRUCTURING_MAX_CONCURRENCY: int = 4

    # --- Question_Attachment_Agent Thresholds ---
    # QUESTION_ATTACHMENT_COSINE_THRESHOLD (2026-08-18) : 0.15 était calibré
    # pour l'ancien embedding factice (hash déterministe, jamais branché sur
    # un vrai modèle) — jamais valide pour de vrais embeddings sémantiques.
    # Testé le 2026-08-16 avec de vrais embeddings (Gemini, autre modèle/
    # dimension que celui utilisé en prod ici) : le delta best/2e-meilleur
    # candidat dépasse rarement 0.15 quand plusieurs questions portent sur
    # un sujet proche — 0.05 a résolu correctement 3/5 blocs de test au
    # Niveau 2, les 2 autres correctement déférés au Niveau 3. Point de
    # départ raisonnable, pas définitif — à revalider empiriquement avec
    # sentence-transformers/all-MiniLM-L6-v2 (app/core/embeddings.py, le
    # modèle réellement branché ici depuis ce même fix).
    QUESTION_ATTACHMENT_COSINE_THRESHOLD: float = 0.05
    # QUESTION_ATTACHMENT_MIN_CONFIDENT_SIMILARITY (2026-09-03) — bug réel
    # constaté sur une vraie copie (zainabsebhi, 2 exercices de treillis très
    # proches en vocabulaire/méthode) : le delta seul (ci-dessus) ne suffit
    # pas à garantir un rattachement fiable quand best_sim lui-même est
    # faible en absolu. 6 blocs appartenant sans ambiguïté à Q1 (formules
    # sin α = 1/√5 identiques à la référence de Q1) ont été rattachés à Q2 —
    # confidence_score (= best_sim) entre 0.235 et 0.549 seulement, mais un
    # delta ≥ 0.05 a suffi à court-circuiter l'arbitrage LLM (Niveau 3), qui
    # aurait correctement distingué les deux exercices sur le contenu réel.
    # best_sim doit désormais AUSSI dépasser ce plancher pour que le Niveau 2
    # conclue seul ; sinon, delta net ou non, on défère toujours au Niveau 3.
    QUESTION_ATTACHMENT_MIN_CONFIDENT_SIMILARITY: float = 0.6
    QUESTION_ATTACHMENT_LABEL_FUZZY_THRESHOLD: int = 80
    QUESTION_ATTACHMENT_ORPHAN_SIMILARITY_THRESHOLD: float = 0.1
    # 120 -> 300 (2026-09-03, test réel zainabsebhi) : _attach_single_block
    # traite les blocs SÉQUENTIELLEMENT (jamais en parallèle, cf. execute()) —
    # 120s suffisait tant que QUESTION_ATTACHMENT_MIN_CONFIDENT_SIMILARITY
    # (ci-dessus) laissait le Niveau 2 conclure seul sur la quasi-totalité
    # des blocs. Avec ce plancher relevé, beaucoup plus de blocs défèrent
    # légitimement au Niveau 3 (arbitrage LLM, plus lent) — constaté en
    # réel : 25 blocs actifs ont fait dépasser 120s (~133s) sans aucune
    # erreur, uniquement par accumulation d'appels LLM réels et corrects.
    # Effet secondaire attendu et acceptable du fix de rattachement, pas un
    # nouveau problème séparé.
    QUESTION_ATTACHMENT_MAX_TIMEOUT_SECONDS: int = 300

    # --- Garde-fous transverses (audit "garanties transverses") ---
    # Plafond d'appels LLM par thread_id, remis à zéro à chaque run (jamais
    # cumulatif à travers les reprises) — cf. Job.llm_call_count.
    MAX_LLM_CALLS_PER_THREAD: int = 30
    # Rate limiting fournisseur (429/413 "rate_limit_exceeded") — distinct de
    # infrastructure_retry (réseau/5xx, backoff court <=10s, cf. app/llm/
    # retry.py). Nombre de tentatives SUR LE MÊME fournisseur avant de
    # basculer sur le suivant de la chaîne (comportement de repli existant
    # préservé, jamais supprimé).
    # 1 = pas de vraie ré-attente sur ce fournisseur, bascule quasi
    # immédiate. Constaté en usage réel (compte Groq gratuit, OCR_VISION) :
    # le "413 Request too large... TPM: Limit 8000, Requested 12363" observé
    # n'est PAS un quota temporaire qui se libère avec l'attente — le
    # prompt+image de ce document (~4363 tokens, fixe) + max_tokens (8000)
    # dépasse le plafond dès la CONSTRUCTION de la requête, indépendamment
    # de l'usage déjà consommé ce cycle. Réessayer le même fournisseur avec
    # la même ModelSpec redemande alors exactement les mêmes tokens et
    # échoue à nouveau, systématiquement — un retry >1 ne fait ici que
    # perdre LLM_RATE_LIMIT_WAIT_SECONDS par tentative pour rien avant la
    # bascule, déjà inévitable, vers le fournisseur suivant.
    LLM_RATE_LIMIT_MAX_RETRIES: int = 1
    # Délai d'attente par défaut (secondes) si le fournisseur n'indique pas
    # lui-même un délai suggéré — jamais figé ailleurs qu'ici.
    LLM_RATE_LIMIT_WAIT_SECONDS: int = 60

    # --- Competency_Assessment_Agent (Niveau 3 : décroissance temporelle) ---
    # Poids de l'observation la plus ancienne d'un rang par rapport à la
    # précédente (0.9^age_en_évaluations) — jamais figé en dur dans le code.
    COMPETENCY_DECAY_FACTOR: Decimal = Decimal("0.9")
    # Écart (en points de pourcentage, échelle 0-100) entre la fenêtre
    # récente et la fenêtre précédente au-delà duquel le trend est
    # IMPROVING/DECLINING plutôt que STABLE.
    COMPETENCY_TREND_THRESHOLD_PERCENT: Decimal = Decimal("5.0")
    # Seuil de performance_copie (échelle 0.0-1.0) en dessous duquel une
    # observation compte comme "faible" pour is_persistent_weakness.
    COMPETENCY_PERSISTENT_WEAKNESS_THRESHOLD: Decimal = Decimal("0.5")
    # Nombre d'observations consécutives les plus récentes devant être
    # toutes sous COMPETENCY_PERSISTENT_WEAKNESS_THRESHOLD.
    COMPETENCY_PERSISTENT_WEAKNESS_WINDOW: int = 3
    # Chantier notation graduée (Partie 3/3) — seuil de completion_ratio
    # (échelle 0.0-1.0) au-dessus duquel un outcome de sous-question compte
    # comme une réussite pour le comptage strengths (_rank_subquestion_
    # pattern) — distinct de COMPETENCY_PERSISTENT_WEAKNESS_THRESHOLD
    # (échelle performance_copie agrégée, pas un outcome individuel).
    COMPETENCY_STRENGTH_RATIO_THRESHOLD: Decimal = Decimal("0.8")
    # Seuil de completion_ratio en dessous duquel un outcome compte comme un
    # échec pour le comptage weaknesses — addressed=False compte toujours
    # comme un échec indépendamment de ce seuil (jamais un ratio deviné sur
    # une absence).
    COMPETENCY_WEAKNESS_RATIO_THRESHOLD: Decimal = Decimal("0.3")

    # --- Recommendation_Agent ---
    # Seuil de mastery_level (échelle 0-100) en dessous duquel une
    # compétence est "faible" (remédiation) — distinct de COMPETENCY_
    # PERSISTENT_WEAKNESS_THRESHOLD (échelle 0.0-1.0, mécanique interne de
    # Competency_Assessment_Agent) : seuil métier propre à la recommandation,
    # jamais réutilisé tel quel pour ne pas coupler les deux agents.
    RECOMMENDATION_WEAK_MASTERY_THRESHOLD: Decimal = Decimal("60.0")
    # Seuil de confidence_level (0.0-1.0) en dessous duquel une compétence à
    # mastery_level élevé n'est PAS traitée comme acquise (vérification).
    RECOMMENDATION_LOW_CONFIDENCE_THRESHOLD: Decimal = Decimal("0.6")
    # Nombre max d'exercices recommandés par compétence faible.
    RECOMMENDATION_MAX_PER_COMPETENCY: int = 2
    # Plafond global sur le nombre de recommandations d'un même passage
    # (les moins prioritaires au-delà sont simplement omises, jamais
    # tronquées arbitrairement — tri par relevance_score décroissant avant coupe).
    RECOMMENDATION_MAX_TOTAL: int = 10

    # --- Intégration NotebookLM (§7, "Feedback Intelligent", best-effort) ---
    # Chemin vers un fichier storage_state.json (format Playwright — cookies
    # + csrf_token + session_id) obtenu par une connexion Google réelle hors
    # code, provisionné en production depuis un secret manager (jamais le
    # contenu des cookies en dur ni dans une variable d'env directe — trop
    # structuré pour ça, un chemin de fichier est le bon niveau
    # d'indirection). None = intégration désactivée, NotebookLMService le
    # détecte et retourne immédiatement sans tenter de connexion (cf. son
    # docstring — jamais un prérequis au reste du pipeline).
    NOTEBOOKLM_STORAGE_PATH: str | None = None

    @property
    def celery_broker_url(self) -> str:
        return str(self.CELERY_BROKER_URL or self.REDIS_URL)

    @property
    def celery_result_backend(self) -> str:
        return str(self.CELERY_RESULT_BACKEND or self.REDIS_URL)


@lru_cache
def get_settings() -> Settings:
    """Singleton : évite de reparser le .env à chaque import du module."""
    return Settings()


settings = get_settings()