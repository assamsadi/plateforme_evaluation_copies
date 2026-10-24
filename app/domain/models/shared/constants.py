"""
Constantes partagées entre repositories (persistance), distinctes des
constantes propres à un agent (tunables de logique métier, ex.
CONTESTATION_RESOLVED_CONFIDENCE_SCORE dans Contestation_Verification_Agent.py) :
un repository ne doit jamais importer depuis app/agents (mauvais sens de
dépendance), donc les valeurs utilisées à la fois par un agent et par un
repository sont dupliquées en constante ici, avec le même nom/la même valeur
numérique par convention plutôt qu'un import croisé.
"""
from decimal import Decimal

# §7 du doc Contestation_Verification_Agent — confidence_score attribué à
# une ExtractionCorrection quand une CorrectionArbitration AMBIGU est résolue
# par le professeur (correction_arbitration_repository.create_and_apply_verdict) :
# la décision humaine devient la nouvelle source de vérité, qu'elle confirme
# ou infirme la réclamation de l'étudiant. Même valeur numérique que
# CONTESTATION_RESOLVED_CONFIDENCE_SCORE côté agent (0.95).
CONTESTATION_RESOLVED_CONFIDENCE_SCORE = Decimal("0.950")
