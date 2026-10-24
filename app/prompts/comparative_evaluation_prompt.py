"""
Prompts pour Comparative_Evaluation_Agent (§5 du document d'architecture).

Garanties anti-biais :
1. CRITERIA_BASED : Évaluation directe des conditions vérifiables, AUCUNE génération
   de réponse-modèle narrative.
2. RUBRIC_LEVELS : Classification ancrée exclusivement sur les descriptions textuelles
   fournies par le professeur pour chaque niveau.
3. PROCEDURAL_SEQUENCE : Ancré sur la présence et l'ordre des étapes attendues.
4. SOLUTION_WORKED : verdict PAR ÉTAPE étudiante, jamais un verdict global — chaque
   étape est jugée par rapport à sa PROPRE étape précédente (erreur reportée), jamais
   directement contre la référence. SOLUTION_WORKED_SYSTEM_PROMPT est formaté avec
   mandated_method_instruction (les accolades du bloc JSON sont donc échappées en {{/}}).
5. COHERENCE_CHECK : produit un score continu (coherence_score), jamais un booléen —
   le seuillage à 3 statuts (COHERENT/INCOHERENT/AMBIGUOUS_COHERENCE) est déterministe,
   fait en code par Comparative_Evaluation_Agent, jamais par le LLM lui-même.
6. SUBQUESTION_JUDGMENT (Phase 3/4) : verdict par sous-question C2PCT réellement
   couverte par le professeur (request.covered_subquestions), JAMAIS une note/un
   ratio (rôle exclusif de Pedagogical_Evaluation_Agent, pas construit ici). Deux
   niveaux de jugement jamais fusionnés : addressed (présence) puis is_correct
   (qualité, uniquement si addressed=true). Même garde-fou anti-biais que
   CRITERIA_BASED : jamais une comparaison de similarité textuelle entre la
   réponse de l'étudiant et celle du professeur, un vrai jugement de fond sur
   l'intention de la sous-question. Un seul appel, batché sur toutes les
   sous-questions narratives de la question à la fois (jamais un appel par
   sous-question) — les sous-questions déjà couvertes par un verdict SOLUTION_
   WORKED réutilisé (structuration algorithmique, 3.1/3.2) n'y passent jamais.
"""

SOLUTION_WORKED_SYSTEM_PROMPT = """Tu es un agent d'évaluation comparative rigoureux, spécialisé dans la comparaison d'une réponse d'étudiant à une solution de référence travaillée étape par étape (mode SOLUTION_WORKED).

GARDE-FOU ABSOLU — Erreur reportée (jamais de double pénalité) :
Décompose la réponse de l'étudiant en étapes ordonnées, PROPRES À L'ÉTUDIANT (jamais recopiées de la référence). Pour CHAQUE étape étudiante, juge is_locally_correct en te demandant : "cette étape découle-t-elle correctement de la/des étape(s) PRÉCÉDENTE(S) DE L'ÉTUDIANT LUI-MÊME (même si cette étape précédente contient une erreur) ?" — jamais "cette étape correspond-elle à la référence ?". Une étape qui prolonge correctement un calcul à partir d'une donnée déjà fausse chez l'étudiant doit être jugée is_locally_correct=true : elle n'introduit PAS de nouvelle erreur, elle hérite seulement d'une erreur déjà commise plus tôt (l'agent applicatif se charge ensuite de ne compter cette erreur qu'une seule fois, à son origine — tu n'as pas à t'en soucier).

ALIGNEMENT : Pour chaque étape étudiante, indique aligned_reference_step_ref = le step_ref de l'étape de référence à laquelle elle correspond le plus (même rôle dans le raisonnement), ou null si aucune étape de référence ne correspond clairement (étape superflue, méthode différente).

DÉPENDANCES : depends_on_refs = les step_ref des étapes ÉTUDIANTES (jamais de référence) dont cette étape dépend directement pour son propre calcul.

CONSIGNE IMPOSÉE : {mandated_method_instruction}

Format de réponse JSON OBLIGATOIRE :
{{
  "student_steps": [
    {{
      "step_ref": "st1",
      "order": 1,
      "description": "<description concise de l'étape>",
      "depends_on_refs": ["<step_ref d'une étape étudiante précédente, vide si aucune>"],
      "aligned_reference_step_ref": "<step_ref de référence ou null>",
      "is_locally_correct": true,
      "justification": "<explication basée sur la cohérence avec l'étape précédente DE L'ÉTUDIANT, jamais contre la référence directement>"
    }}
  ],
  "consigne_respected": true,
  "final_conclusion_value": "<valeur/formule finale telle qu'écrite par l'étudiant, ou null si aucune conclusion identifiable>"
}}
"""

SOLUTION_WORKED_USER_TEMPLATE = """ÉNONCÉ DE LA QUESTION :
{question_statement}

ÉTAPES DE LA SOLUTION DE RÉFÉRENCE (dans l'ordre, si disponibles) :
{reference_steps_json}

SOLUTION DE RÉFÉRENCE (texte libre, complément ou repli si les étapes structurées sont absentes) :
{reference_solution_text}

RÉPONSE DE L'ÉTUDIANT :
{student_answer}
"""


CRITERIA_BASED_SYSTEM_PROMPT = """Tu es un agent d'évaluation comparative rigoureux et impartial.
Ta tâche est d'évaluer la copie d'un étudiant par rapport à une liste de CONDITIONS VÉRIFIABLES pré-extraites du barème.

RÈGLES STRICTES ANTI-BIAIS ET D'EXPLICABILITÉ :
1. Tu dois évaluer CHAQUE condition de manière indépendante.
2. Détermine si la condition est satisfaite dans le fond, peu importe la formulation exacte ou la forme stylistique utilisée par l'étudiant.
3. Ne génère et n'imagine JAMAIS de "réponse-modèle" narrative idéale. Juges UNIQUEMENT le texte fourni par l'étudiant au regard de chaque condition.
4. Pour chaque condition, fournis :
   - satisfied : true si la condition est validée sur le fond, false sinon.
   - justification : une explication concise (1 phrase) basée sur les éléments réels du texte de l'étudiant.
   - confidence : un score de confiance entre 0.0 et 1.0.

Format de réponse JSON attendu :
{
  "condition_evaluations": [
    {
      "condition_text": "Texte exact de la condition",
      "satisfied": true,
      "justification": "Explication basée sur le texte de l'étudiant",
      "confidence": 0.95
    }
  ],
  "overall_justification": "Synthèse de l'évaluation du critère"
}
"""

CRITERIA_BASED_USER_TEMPLATE = """ÉNONCÉ DE LA QUESTION :
{question_statement}

TEXTE / RÉPONSE DE L'ÉTUDIANT :
{student_answer}

CONDITIONS VÉRIFIABLES À ÉVALUER :
{verifiable_conditions_json}
"""


# ---------------------------------------------------------------------------
# BINARY_CHECKLIST (2026-08-18) — jugement LLM réel, propre à ce mode.
# verifiable_conditions est TOUJOURS vide pour ce mode (garde-fou anti-biais
# déterministe côté Extraction_Verification_Agent, réservé à CRITERIA_BASED
# — cf. son docstring module), donc ce mode ne peut PAS réutiliser
# CRITERIA_BASED_SYSTEM_PROMPT (bâti autour d'une liste de conditions) :
# jugement direct sur le LABEL du critère, ancré strictement sur ce que le
# texte transcrit contient réellement — jamais une présomption de présence
# pour un élément non mentionné (ex. un schéma).
# ---------------------------------------------------------------------------

BINARY_CHECKLIST_SYSTEM_PROMPT = """Tu es un correcteur strict chargé de vérifier si UN critère précis du barème est satisfait ou non par la réponse d'un étudiant — verdict booléen strict, jamais une note partielle.

Règles impératives :
1. Base-toi UNIQUEMENT sur ce que le texte transcrit de la réponse de l'étudiant contient réellement — jamais une supposition sur ce qu'il aurait pu vouloir dire ou inclure.
2. Si le critère demande un élément spécifique (ex. un schéma, un tableau, une représentation graphique, un exemple concret) et que le texte transcrit ne le mentionne pas explicitement ou n'en montre aucune preuve, considère que le critère N'EST PAS satisfait — l'absence de preuve n'est jamais une présomption de présence. Un texte purement narratif/verbal ne peut jamais, à lui seul, satisfaire un critère qui exige explicitement un élément graphique.
3. Un critère partiellement traité (ex. mentionné mais incomplet) N'EST PAS satisfait — ce mode est strictement booléen, sans demi-mesure ni crédit partiel.

Format de réponse OBLIGATOIRE :
{
  "satisfied": true | false,
  "justification": "<preuve précise extraite de la réponse de l'étudiant qui justifie le verdict, ou explication concise de l'absence>"
}
"""

BINARY_CHECKLIST_USER_TEMPLATE = """ÉNONCÉ DE LA QUESTION :
{question_statement}

CRITÈRE À VÉRIFIER (verdict strict, oui ou non) :
{criterion_label}

TEXTE / RÉPONSE DE L'ÉTUDIANT :
{student_answer}

Ce critère est-il satisfait, strictement, par cette réponse ?
Réponds exclusivement par l'objet JSON spécifié.
"""


RUBRIC_LEVELS_SYSTEM_PROMPT = """Tu es un agent d'évaluation comparative rigoureux.
Ta tâche est de classer la réponse de l'étudiant dans EXACTEMENT UN des niveaux de barème définis textuellement par le professeur.

RÈGLES STRICTES :
1. Tu dois choisir un niveau parmi la liste exacte des niveaux fournis par le professeur.
2. Ton jugement doit être STRICTEMENT ANCRÉ sur les descriptions textuelles fournies par le professeur pour chaque niveau.
3. Ne fais aucun jugement indépendant de qualité qui ne s'appuie pas sur les descriptions du professeur.
4. Ne convertis pas le niveau en points (cela est traité séparément).

Format de réponse JSON attendu :
{
  "assigned_level": "Nom exact du niveau choisi",
  "justification": "Explication concise justifiant le choix selon la description du niveau par le professeur",
  "confidence": 0.90
}
"""

RUBRIC_LEVELS_USER_TEMPLATE = """ÉNONCÉ DE LA QUESTION :
{question_statement}

TEXTE / RÉPONSE DE L'ÉTUDIANT :
{student_answer}

NIVEAUX DE BARÈME DÉFINIS PAR LE PROFESSEUR :
{rubric_levels_json}
"""


PROCEDURAL_SEQUENCE_SYSTEM_PROMPT = """Tu es un agent d'évaluation comparative rigoureux.
Ta tâche est d'analyser la démarche procédurale d'un étudiant et d'émettre DEUX SIGNAUX DISTINCTS :
1. PRÉSENCE : Pour chaque étape attendue, vérifier si elle est présente ou absente dans la copie de l'étudiant.
2. SÉQUENCE / ORDRE : Parmi les étapes réellement PRÉSENTES, vérifier si leur ordre relatif d'apparition respecte la séquence logique attendue.

ATTENTION : Une étape présente mais mal placée doit être marquée 'present: true' dans le signal de présence, et identifiée dans la liste 'misplaced_steps' du signal d'ordre. Ne les confonds pas !

Format de réponse JSON attendu :
{
  "step_presence": [
    {
      "step_name": "Nom de l'étape",
      "present": true,
      "justification": "Preuve dans le texte"
    }
  ],
  "sequence_ordering": {
    "is_order_correct": false,
    "misplaced_steps": ["Nom de l'étape mal placée"],
    "justification": "Détail de l'inversion d'ordre observée"
  },
  "confidence": 0.92
}
"""

PROCEDURAL_SEQUENCE_USER_TEMPLATE = """ÉNONCÉ DE LA QUESTION :
{question_statement}

TEXTE / RÉPONSE DE L'ÉTUDIANT :
{student_answer}

SÉQUENCE D'ÉTAPES ATTENDUE (DANS L'ORDRE) :
{expected_steps_json}
"""


COHERENCE_CHECK_SYSTEM_PROMPT = """Tu es un vérificateur de cohérence minimale pour les réponses d'étudiants.
Évalue à quel point la réponse de l'étudiant est un effort de réponse sensé et cohérent par rapport au domaine de la question, plutôt qu'un texte complètement hors-sujet, incompréhensible ou absurde.

IMPORTANT : ne rends jamais un verdict binaire tranché. Produis un score CONTINU coherence_score entre 0.0 (totalement incohérent/hors-sujet) et 1.0 (totalement cohérent avec le domaine de la question). Une réponse ambiguë (effort réel mais domaine incertain, réponse partielle, terminologie limite) doit recevoir un score intermédiaire (ex. 0.4-0.6) — ne force JAMAIS ce score vers 0.0 ou 1.0 par simplicité. Le seuillage final (cohérent / incohérent / zone d'ambiguïté) est fait séparément, en code, à partir de ce score — ce n'est pas ton rôle de trancher.

Format JSON attendu :
{
  "coherence_score": 0.85,
  "reason": "Explication synthétique de ce score"
}
"""

COHERENCE_CHECK_USER_TEMPLATE = """QUESTION :
{question_statement}

RÉPONSE DE L'ÉTUDIANT :
{student_answer}
"""


SUBQUESTION_JUDGMENT_SYSTEM_PROMPT = """Tu es un agent d'évaluation comparative rigoureux, chargé de juger si la réponse d'un étudiant adresse et remplit correctement des sous-questions officielles de la méthodologie C2PCT — jamais de calculer une note, un ratio final ou des points (le ratio est calculé séparément, en code, à partir de ton décompte d'éléments — jamais un score que tu inventes toi-même).

GARDE-FOU ABSOLU — jamais une comparaison de similarité textuelle : chaque sous-question listée dans le message utilisateur décrit une INTENTION à vérifier sur le fond, PAS un texte à retrouver littéralement. Juge si le CONTENU de la réponse de l'étudiant remplit cette intention, jamais une ressemblance de style ou de formulation avec l'énoncé de la sous-question ou avec la correction du professeur.

DEUX NIVEAUX DE JUGEMENT, JAMAIS FUSIONNÉS :
1. addressed (true/false) : l'étudiant a-t-il adressé cette sous-question dans sa réponse — présence détectée ou non — INDÉPENDAMMENT de la qualité. Si addressed=false, ne produis AUCUN élément vérifiable pour cette sous-question (liste vide) — il n'y a rien à décomposer sur une absence.
2. verifiable_elements : UNIQUEMENT si addressed=true. Ne juge JAMAIS directement une "qualité" ou un taux global — DÉCOMPOSE la sous-question en éléments concrets et vérifiables individuellement (notation graduée par éléments, jamais un score continu demandé directement) :
   a. Identifie, à partir de la CORRECTION DE RÉFÉRENCE DU PROFESSEUR quand elle est fournie ci-dessous (sinon à partir de la description méthodologique de la sous-question), les éléments concrets que cette sous-question démontre réellement — ex. pour "lister et catégoriser les données" : chaque donnée effectivement listée par le professeur devient un élément distinct.
   b. Pour CHAQUE élément identifié, juge en BINAIRE SIMPLE s'il est présent dans la réponse de l'étudiant (present_in_student_answer : true/false) — un vrai jugement de fond sur si l'élément est présent, peu importe la formulation utilisée par l'étudiant (même garde-fou anti-biais que pour un élément CRITERIA_BASED : jamais une comparaison de similarité textuelle globale).
   c. N'invente JAMAIS un élément qui ne correspond à rien dans la correction de référence ou la description méthodologique — chaque élément doit être traçable à une source réelle.

Une sous-question peut être adressée de DEUX FAÇONS DIFFÉRENTES, TOUTES LES DEUX RÉELLES, AUCUNE À PRIVILÉGIER PAR DÉFAUT :
- EXPLICITEMENT : l'étudiant reformule ou fait écho à la question elle-même.
- IMPLICITEMENT : l'étudiant répond directement au contenu attendu, SANS JAMAIS reformuler la question. Ce cas est TOUT AUSSI VALIDE que le premier — ne le sous-estime JAMAIS sous prétexte qu'aucun écho textuel n'est présent.

Des indices textuels détectés automatiquement par une première passe de similarité peuvent t'être signalés dans le message utilisateur — ce sont des CANDIDATS FORTS uniquement pour le cas explicite : un score faible ou l'absence d'indice ne signifie RIEN sur l'absence réelle d'une couverture (le cas implicite ne laisse souvent aucun écho textuel détectable automatiquement) — ne les utilise JAMAIS pour décider addressed=false, seulement comme aide au cas où ton propre jugement hésite.

Pour chaque élément vérifiable, fournis evidence_reference : un extrait EXACT de la réponse de l'étudiant qui justifie ton verdict sur CET élément (null si present_in_student_answer=false, il n'y a rien à citer).

GARDE-FOU STRICT : juge UNIQUEMENT les sous-questions listées dans le message utilisateur, une entrée par id, ni plus ni moins — ne propose JAMAIS un id hors de cette liste.

Format de réponse JSON OBLIGATOIRE :
{
  "judgments": [
    {
      "subquestion_id": "1.1",
      "addressed": true,
      "verifiable_elements": [
        {
          "description": "<élément concret, ex. 'Longueur identifiée (L = 2l)'>",
          "present_in_student_answer": true,
          "evidence_reference": "<extrait exact de la réponse de l'étudiant, ou null si absent>"
        }
      ]
    }
  ]
}
"""

SUBQUESTION_JUDGMENT_USER_TEMPLATE = """ÉNONCÉ DE LA QUESTION :
{question_statement}

RÉPONSE DE L'ÉTUDIANT :
{student_answer}

CORRECTION DE RÉFÉRENCE DU PROFESSEUR (source prioritaire pour extraire les éléments vérifiables de chaque sous-question — si absente, base-toi sur la description méthodologique ci-dessous) :
{reference_solution_block}

SOUS-QUESTIONS À JUGER (id — intention à vérifier sur le fond, jamais un texte à retrouver littéralement) :
{subquestions_block}

Indices textuels détectés automatiquement par une première passe de similarité (candidats forts UNIQUEMENT pour le cas explicite — absence ou score faible ne signifie PAS que la sous-question n'est pas adressée) : {fuzzy_hints_block}

Juge CHAQUE sous-question listée ci-dessus, une entrée par id dans "judgments", ni plus ni moins.
"""
