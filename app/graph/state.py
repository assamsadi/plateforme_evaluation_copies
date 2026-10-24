from typing import Literal, Optional
from pydantic import BaseModel
from datetime import datetime

class QuestionScore(BaseModel):
    question_id: str
    points_obtained: float
    points_max: float
    criteria_scores: dict[str, float]      # ex: {"exactitude": 4, "coherence": 3}

class C2PCTSkillEvaluation(BaseModel):
    skill: Literal[
        "decomposition", "pattern_recognition", "abstraction",
        "algorithmic_thinking", "evaluation", "generalization"
    ]
    expected_by_teacher: bool               # cette competence est-elle attendue sur CETTE question ?
    expected_weight: Optional[float] = None # ponderation si le prof en fournit une (optionnel)
    observed_level: Literal[
        "MASTERED", "PARTIALLY_MASTERED", "NOT_OBSERVED", "MISAPPLIED"
    ]
    confidence: float                       # confiance du systeme sur cette detection
    evidence: Optional[str] = None          # extrait/justification tire de la copie etudiante

class QuestionC2PCTEvaluation(BaseModel):
    question_id: str
    skill_evaluations: list[C2PCTSkillEvaluation]   # TOUJOURS les 6 competences, systematiquement
                                                     # evaluees, pas seulement celles attendues

class TriageVerdict(BaseModel):
    question_id: str
    zone_id: str                            # identifiant de la zone/crop concernee
    ocr_prediction: str
    student_correction: str
    verdict: Literal["PLAUSIBLE", "IMPLAUSIBLE", "AMBIGU"]
    confidence: float
    justification: str                      # sortie du VLM, pour audit

class PipelineState(BaseModel):
    # --- Identite / routing ---
    thread_id: str                          # = exercise_id OU submission_id selon flow_type
    flow_type: Literal["exercise_setup", "student_evaluation"]
    trace_id: str                           # propage pour observabilite

    # --- References ---
    exercise_id: Optional[str] = None       # toujours renseigne (cree ou reference)
    submission_id: Optional[str] = None     # renseigne seulement en student_evaluation
    module_id: str
    professor_id: Optional[str] = None      # renseigne en exercise_setup
    student_id: Optional[str] = None        # renseigne en student_evaluation

    # --- Fichiers source ---
    raw_file_path: str                      # chemin MinIO du scan brut
    # Ajouté lors du câblage réel : les deux agents OCR (prof et étudiant)
    # prennent mime_type en paramètre direct — champ manquant à la conception
    # initiale, requis pour construire l'état initial du graph depuis la
    # tâche Celery (exercise_tasks.py/submission_tasks.py transmettent déjà
    # mime_type aujourd'hui).
    mime_type: str = "application/pdf"

    # --- OCR / extraction ---
    # Corrigé lors du câblage réel du graph (pipeline_graph.py) : OCR_Extraction_
    # Agent.execute() renvoie list[RawExtractedBlock] (Pydantic), jamais un dict
    # unique — champ renommé/retypé en conséquence (aucun producteur/consommateur
    # existant ne dépendait de l'ancienne forme "ocr_raw_output: dict"). Chaque
    # élément est un RawExtractedBlock.model_dump(mode="json") ; reconstruit via
    # RawExtractedBlock.model_validate(...) par le nœud consommateur.
    raw_extracted_blocks: list[dict] = []
    assembled_document: Optional[dict] = None  # texte/equations/schemas assembles

    # --- Structuration (exercise_setup, Document_Structuring_Agent) ---
    # Signal minimal pour le routage conditionnel (edge INCOMPLETE -> pause) ;
    # le StructuringReport complet est persisté par le service, pas dupliqué ici.
    structuring_status: Optional[Literal["COMPLETE", "INCOMPLETE"]] = None

    # --- HITL (les 2 flux) ---
    # Élargi lors du câblage réel du graph : les 3 valeurs d'origine ne
    # couvraient que student_evaluation (commentaire de conception initial),
    # mais document_structuring_node/extraction_verification_node ont
    # exactement le même besoin de pause côté exercise_setup — un seul champ
    # discriminé par valeur plutôt qu'un champ dupliqué par flow_type (même
    # principe que flow_type lui-même, cf. diagnostic : jamais deux structures
    # parallèles pour représenter les 2 flux).
    pending_action: Optional[Literal[
        "student_verification", "teacher_validation", "teacher_arbitration",
        "structuring_incomplete", "clarification_review",
    ]] = None
    student_corrections: Optional[list[dict]] = None   # corrections proposees par l'etudiant
    triage_verdicts: list[TriageVerdict] = []
    arbitration_required: bool = False
    arbitration_resolution: Optional[dict] = None      # decision finale du prof si ambigu
    # Ajouté lors du câblage réel (branche student_evaluation) : signal posé
    # par await_student_verification_node à partir du payload de reprise
    # (Command(resume=...)), lu par la edge conditionnelle qui suit pour
    # décider de router vers contestation_verification_node ou non — un
    # payload de reprise n'est lisible que DANS le nœud qui a appelé
    # interrupt(), jamais dans une fonction de routing (routing.py), d'où ce
    # champ de transit plutôt qu'une lecture directe du payload par l'edge.
    contestation_check_requested: bool = False

    # --- Decomposition / questions ---
    questions: list[dict] = []              # {question_id, text, ...}

    # --- Verification d'extraction (exercise_setup, Extraction_Verification_Agent) ---
    # Signal minimal pour le routage conditionnel (edge BLOCKING -> pause) ;
    # le detail des ClarificationRequest est persiste par le service, pas
    # duplique ici (meme principe que structuring_status ci-dessus).
    blocking_clarification_count: int = 0

    # --- Bareme / C2PCT attendu (exercise_setup, fourni par le prof) ---
    bareme_input: Optional[dict] = None     # points par question/critere, saisi par le prof
    c2pct_expected_input: Optional[dict] = None
    # structure : { question_id: { skill: {expected: bool, weight: float | null} pour les 6 skills } }
    # saisi par le prof, question par question, competence par competence

    # --- Variantes / Graphe de raisonnement (exercise_setup) ---
    exercise_variant_mode: Literal["PROACTIVE_WITH_FALLBACK", "ON_DEMAND_ONLY"] = "PROACTIVE_WITH_FALLBACK"
    student_candidate_method: Optional[dict] = None  # Pour le déclencheur à la demande (2.2)
    generated_variants: Optional[list[dict]] = None
    validated_variants: Optional[list[dict]] = None    # apres validation prof
    pending_reasoning_graph_variant_ids: list[str] = []  # IDs des SolutionVariant de référence à retraiter lors de la reprise
    reasoning_graph_retry_counts: dict[str, int] = {}    # Compteur de tentatives de reprise par variant_id (anti-boucle)

    # --- Comparaison / evaluation (student_evaluation) ---
    # Câblage workflow (Priorité 1, chantier C2PCT) : champ existant mais
    # jamais utilisé jusqu'ici (confirmé par recherche) — porte désormais la
    # projection minimale posée par comparative_evaluation_node (bareme_id/
    # bareme_points/covered_subquestions/subquestion_judgments par question),
    # consommée par evaluation_node juste après. Le détail complet du
    # rapport Comparative_Evaluation_Agent n'est PAS conservé ici (cf.
    # docstring comparative_evaluation_node).
    comparison_results: Optional[list[dict]] = None
    # question_scores/c2pct_evaluations ci-dessous restent de la conception
    # ORIGINALE (avant la découverte de la vraie méthodologie C2PCT/CHAABI à
    # 7 compétences — C2PCTSkillEvaluation.skill n'en liste que 6, sous des
    # noms différents) : jamais utilisés nulle part (confirmé), non touchés
    # ici (hors mandat de ce ticket — câblage, pas nettoyage de state).
    question_scores: list[QuestionScore] = []
    c2pct_evaluations: list[QuestionC2PCTEvaluation] = []   # renomme depuis c2pct_matches :
                                                             # evaluation detaillee par competence,
                                                             # pas un statut global par question

    # --- Feedback / recommandation ---
    feedback_text: Optional[str] = None
    recommended_exercise_ids: list[str] = []

    # --- Statut d'execution ---
    status: Literal["RUNNING", "PAUSED", "COMPLETED", "FAILED"] = "RUNNING"
    paused_at_node: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime