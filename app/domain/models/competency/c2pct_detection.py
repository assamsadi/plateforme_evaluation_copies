"""
c2pct_detection — mécanisme de détection hybride (rapidfuzz + jugement LLM
sur l'intention) des sous-questions officielles C2PCT, FACTORISÉ pour être
PARTAGÉ entre :
  - Extraction_Verification_Agent (Phase 2/4) : texte du professeur
    (énoncé + correction) -> covered_subquestions.
  - Comparative_Evaluation_Agent (Phase 3/4) : texte de l'étudiant ->
    jugement addressed/is_correct par sous-question.

Extrait ici plutôt que dupliqué une deuxième fois entre agents — même
principe déjà appliqué (canonical_form réutilisé via ExtractionVerification
Agent._compute_canonical_form dans le ticket bugs critiques). Volontairement
SÉPARÉ de c2pct_scaffold.py : ce dernier reste PUREMENT données + accesseurs
(Phase 1, contrat explicite "aucune détection, aucun matching, aucune
logique métier ici") — la logique de détection vit dans ce module distinct,
qui dépend de c2pct_scaffold.py, jamais l'inverse.

Ce module ne fait QUE le premier passage déterministe (indice, jamais un
filtre) : le jugement LLM sur l'intention (rôle principal) reste propre à
chaque agent (prompts différents, textes différents, appels LLM différents
— pas de mutualisation possible ni souhaitable à ce niveau).
"""
import re

from rapidfuzz import fuzz

from app.domain.models.competency.c2pct_scaffold import get_all_subquestions

# Seuil empirique de calibration (même statut que les autres seuils de ce
# codebase, ex. rag_repository.similarity_threshold) — n'exclut JAMAIS rien,
# alimente seulement un indice transmis au LLM. Valeur d'origine (Phase 2).
SUBQUESTION_FUZZY_THRESHOLD = 70


def fuzzy_candidate_subquestions(
    text: str, threshold: int = SUBQUESTION_FUZZY_THRESHOLD,
) -> set[str]:
    """
    Premier passage déterministe, UNIQUEMENT utile au cas où le texte
    (professeur OU étudiant, peu importe la source) fait écho EXPLICITEMENT
    au texte d'une sous-question officielle. Un score faible ou l'absence de
    candidat ici ne signifie RIEN sur l'absence réelle de la sous-question —
    une couverture IMPLICITE (réponse directe au contenu attendu, sans
    jamais reformuler la question) reste possible et n'a aucune raison de
    matcher textuellement. Jamais utilisé pour exclure : sert uniquement
    d'indice transmis en contexte au LLM (rôle principal de la détection).
    """
    if not text or not text.strip():
        return set()

    segments = [s.strip() for s in re.split(r"[.!?\n]+", text) if s.strip()]
    if not segments:
        segments = [text]

    candidates: set[str] = set()
    for sq in get_all_subquestions():
        best_score = max(
            (fuzz.token_set_ratio(segment, sq.reference_prompt) for segment in segments),
            default=0,
        )
        if best_score >= threshold:
            candidates.add(sq.id)
    return candidates
