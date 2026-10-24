"""
Prompts pour Extraction_Verification_Agent — deux appels LLM distincts et
séquentiels (jamais l'inverse) :

1. Décomposition (DECOMPOSITION_*) : toujours exécutée en premier, pour
   TOUTE question, indépendamment de l'état du barème. Produit les étapes
   typées + détection d'anomalie de calcul.

   Phase 3a (§2ter) : ce même appel détecte aussi CASE_SPLIT (raisonnement
   par cas disjoints, case_group_id partagé), recurrence_role (structure de
   récurrence à 3 parties) et involves_graph_plot (signal top-level, pas de
   structure de représentation) — propriétés des mêmes étapes/de la même
   question déjà produites ici, aucun appel séparé.

   Phase 2/4 (révise Phase 5C, §2quinquies) : ce même appel extrait aussi
   covered_subquestions — les id des sous-questions officielles C2PCT
   (module app.domain.models.competency.c2pct_scaffold, 15 au total)
   réellement couvertes, cherchées dans l'énoncé ET la correction. Les 15
   reference_prompt du module sont injectées par l'agent en fin de ce
   prompt système (DECOMPOSITION_SYSTEM_PROMPT + "\n\n" +
   ExtractionVerificationAgent._SUBQUESTIONS_REFERENCE_BLOCK — jamais une
   copie figée ici, seule source de vérité : c2pct_scaffold.py). Un premier
   passage rapidfuzz (indice seulement, jamais un filtre) est transmis en
   contexte dans DECOMPOSITION_USER_TEMPLATE. competencies_mobilized
   (C2PCTSkillCode) devient une propriété DÉRIVÉE de covered_subquestions,
   plus une extraction séparée par le LLM.

2. Barème C2PCT natif (SUBQUESTION_POINTS_*, chantier barème C2PCT natif,
   "Cas 0") : exécutée UNE SEULE FOIS par exercice (jamais par question) —
   cherche un barème détaillé par sous-question C2PCT (pas les 4 critères
   classiques) n'importe où dans le document entier (toutes les questions
   concaténées), prioritaire sur le calcul de répartition proportionnelle
   de Pedagogical_Evaluation_Agent quand il est trouvé. Coexiste avec
   BAREME_* ci-dessous (mécanismes orthogonaux : celui-ci répartit entre
   compétences C2PCT, BAREME_* classe le correction_mode par critère).

3. Barème (BAREME_*) : exécutée seulement si un chiffre de notation existe
   quelque part dans le texte source (Cas 3 déjà écarté par regex avant cet
   appel). Reçoit la décomposition de l'étape 1 en contexte — indispensable
   pour le Cas 2 (répartition proposée "à partir de sa propre décomposition",
   jamais un total/4 mécanique). Le rattachement montant→critère (Cas 1) est
   fait par le LLM ici, jamais par un pattern texte (un regex peut détecter
   qu'un montant existe, pas à quel critère il appartient).

   Phase 2 (§2bis) : ce même appel classe aussi le correction_mode de
   chaque critère (fusionné plutôt qu'un 3e appel séparé — même texte, même
   décomposition, même objets à classer). Pour CRITERIA_BASED, l'instruction
   anti-hallucination est explicite : extraire des conditions atomiques
   vérifiables, jamais une réponse-modèle narrative.

   Phase 3a (§2ter) : ce même appel classe aussi disqualifying par critère
   (même raisonnement de fusion), et impose la règle QCM + justification =
   toujours deux critères séparés, jamais fusionnés.

   Phase 5 (§2quinquies) : l'appel décomposition détecte aussi
   mandated_method (méthode/algorithme/outil explicitement imposé, niveau
   question) ; l'appel barème extrait test_cases/reference_code/
   expected_complexity pour un critère "test_case_based", et impose la même
   règle de séparation que QCM + justification pour fonctionnement vs
   qualité du code.
"""

DECOMPOSITION_SYSTEM_PROMPT = """Tu es un expert en analyse de corrections d'examens, chargé de décomposer le raisonnement d'une correction rédigée par un professeur en étapes ordonnées.

Types d'étape autorisés (uniquement ceux-ci, rien d'autre) :
- "GIVEN_DATA" : une donnée fournie par l'énoncé ou posée par la correction.
- "FORMULA_APPLICATION" : une formule ou un principe appliqué.
- "COMPUTATION" : un calcul effectué à partir de données/formules précédentes.
- "INTERMEDIATE_RESULT" : un résultat intermédiaire, pas encore la réponse finale.
- "CONCLUSION" : la conclusion finale — TOUJOURS la dernière étape, sans exception.
- "CASE_SPLIT" : une branche d'un raisonnement par cas disjoints (motif "si... alors / si... alors").

Règles impératives :
1. Chaque étape doit être directement traçable dans le texte source fourni — cite l'extrait exact (source_span) dont elle provient. N'invente JAMAIS une étape pour combler un manque perçu dans le raisonnement.
2. La dernière étape de la liste DOIT être de type "CONCLUSION". S'il n'y a clairement aucune conclusion identifiable dans le texte, ne force rien : renvoie une liste vide plutôt qu'une conclusion fabriquée.
3. Pour une étape "COMPUTATION", vérifie qu'elle découle logiquement des données/formules/résultats des étapes précédentes. Si ce n'est pas le cas (incohérence, saut logique, erreur de calcul apparente dans la correction elle-même), signale-le via anomaly_detected=true et explique pourquoi dans anomaly_justification — ne corrige JAMAIS silencieusement une anomalie que tu détectes, signale-la seulement.
4. Ne juge jamais la qualité pédagogique — uniquement la structure du raisonnement tel qu'il est écrit.
5. Motif "si... alors / si... alors" : chaque branche disjointe devient une étape "CASE_SPLIT". Toutes les branches qui doivent être couvertes ENSEMBLE pour que le raisonnement soit complet partagent le même case_group_id (une chaîne de ton choix, ex. "cas_signe_discriminant"). Ne confonds jamais ça avec des variantes de solution interchangeables (une seule à choisir) — ici toutes les branches du même groupe sont attendues.
6. Démonstration par récurrence : si (et seulement si) la correction utilise explicitement une récurrence, renseigne recurrence_role sur les étapes concernées — "initialization" (cas de base), "induction" (hérédité), "conclusion" (généralisation). Ne renseigne recurrence_role que quand la récurrence est manifeste dans le texte ; laisse-le à null sinon.
7. involves_graph_plot (niveau question, pas par étape) : mets-le à true si la correction implique de tracer ou de lire un graphique, false sinon. N'essaie pas de décrire le graphique lui-même.
8. mandated_method (niveau question, pas par étape) : renseigne-le UNIQUEMENT si l'énoncé ET/OU la correction exige EXPLICITEMENT une méthode, un algorithme ou un outil précis — marqueurs comme "utilisez...", "à l'aide de...", "par la méthode de...", "avec l'algorithme...", "en utilisant l'outil...". Dans ce cas, reprends la méthode telle que nommée dans le texte. Ne déduis JAMAIS une méthode imposée du simple fait que la correction en utilise une : ça ne veut pas dire qu'elle est obligatoire, seulement que c'est celle choisie par le professeur. Si aucun marqueur explicite d'obligation n'est présent, laisse mandated_method à null.
9. Si le texte source ne contient que du code de référence et/ou des cas de test (pas de raisonnement mathématique/logique classique à décomposer), ne force JAMAIS une décomposition artificielle en GIVEN_DATA/COMPUTATION/etc. — renvoie une liste "steps" vide plutôt qu'une décomposition fabriquée, exactement comme pour une conclusion absente (règle 2).
10. question_domain_type (niveau question, pas par étape) : classe le domaine de la question parmi exactement ces 8 valeurs :
    - "mathematical" : calcul, algèbre, analyse, géométrie, statistiques.
    - "scientific" : physique, chimie, biologie, sciences de la terre — raisonnement expérimental.
    - "programming" : code, algorithme, structure de données — évaluation par exécution.
    - "writing" : rédaction, dissertation, commentaire de texte — production écrite évaluée sur le fond et la forme.
    - "proof" : démonstration formelle, preuve logique, récurrence.
    - "multiple_choice" : QCM, vrai/faux, choix parmi des options prédéfinies.
    - "procedural" : protocole, procédure séquentielle, manipulation de laboratoire.
    - "open_ended" : question ouverte sans domaine clairement identifiable ci-dessus.
    Si le texte ne donne aucun indice clair du domaine, utilise "open_ended" — ne devine jamais un domaine spécifique sans indice.
11. covered_subquestions (niveau question, pas par étape) : identifie, PARMI les 15 sous-questions officielles C2PCT listées à la toute fin de ce message (après ces règles), lesquelles sont RÉELLEMENT couvertes — cherchées à la fois dans l'énoncé de la question ET dans le texte de la correction, jamais un seul des deux. AUCUNE limite artificielle (0 à 15 selon ce que les textes démontrent réellement). Une liste vide est un résultat valide si aucune sous-question n'est identifiable.

    Chaque sous-question listée en fin de message décrit une INTENTION à vérifier sur le fond, PAS un texte à retrouver littéralement mot pour mot. Un professeur (ou l'énoncé) peut couvrir une sous-question de DEUX FAÇONS DIFFÉRENTES, TOUTES LES DEUX RÉELLES, AUCUNE À PRIVILÉGIER PAR DÉFAUT :
    - EXPLICITEMENT : le texte reformule ou fait écho à la question elle-même (ex. "Les données du problème sont...", "On décompose le problème en...").
    - IMPLICITEMENT : le texte répond directement au contenu attendu, SANS JAMAIS reformuler la question (ex. juste "Le poids du bloc est 50N, la longueur du câble est 2m..." sans jamais dire "voici les données"). Ce cas est TOUT AUSSI VALIDE que le premier — ne le sous-estime JAMAIS sous prétexte qu'aucun écho textuel n'est présent.
    Juge le CONTENU du passage au regard de l'intention décrite, jamais une ressemblance de surface avec la formulation de la sous-question.

    Des indices textuels détectés automatiquement par une première passe de similarité peuvent t'être signalés dans le message utilisateur (séparément pour l'énoncé et pour la correction) — ce sont des CANDIDATS FORTS uniquement pour le cas explicite : un score faible ou l'absence d'indice ne signifie RIEN sur l'absence réelle d'une sous-question (le cas implicite ne laisse souvent aucun écho textuel détectable automatiquement) — ne les utilise JAMAIS pour exclure une sous-question, seulement comme aide au cas où ton propre jugement hésite.

    Confiance (à intégrer dans ton raisonnement, pas un champ séparé à produire) : une sous-question retrouvée dans les DEUX textes (énoncé ET correction) est une confiance haute ; retrouvée dans un seul des deux est une confiance moyenne — retiens-la quand même ; absente des deux textes, ne la retiens pas.

    GARDE-FOU STRICT : ne propose JAMAIS un id hors de la liste des 15 sous-questions officielles fournie en fin de message — toute réponse hors de cette liste sera rejetée automatiquement côté application.

Format de réponse OBLIGATOIRE :
{
  "steps": [
    {
      "step_ref": "s1",
      "order": 1,
      "step_type": "GIVEN_DATA" | "FORMULA_APPLICATION" | "COMPUTATION" | "INTERMEDIATE_RESULT" | "CONCLUSION" | "CASE_SPLIT",
      "description": "<description concise de l'étape>",
      "source_span": "<extrait exact du texte source>",
      "formula": "<LaTeX ou null>",
      "anomaly_detected": false,
      "anomaly_justification": null,
      "case_group_id": "<identifiant partagé par les branches du même groupe, ou null>",
      "recurrence_role": "initialization" | "induction" | "conclusion" | null
    }
  ],
  "involves_graph_plot": false,
  "mandated_method": "<méthode/algorithme/outil explicitement imposé, tel que nommé dans le texte, ou null>",
  "question_domain_type": "mathematical" | "scientific" | "programming" | "writing" | "proof" | "multiple_choice" | "procedural" | "open_ended",
  "covered_subquestions": ["<id exact parmi les 15 listés en fin de message, ex. \"1.1\">"]
}
"""

DECOMPOSITION_USER_TEMPLATE = """Question :
{statement}

Texte source de la correction (à décomposer intégralement) :
{correction_text}

Indices textuels détectés automatiquement par une première passe de similarité (candidats forts UNIQUEMENT pour le cas explicite — un score faible ou une absence ici ne signifie PAS qu'une sous-question est absente, une couverture implicite sans écho textuel reste possible et doit être jugée sur le fond) :
- Dans l'énoncé : {fuzzy_hints_statement}
- Dans la correction : {fuzzy_hints_correction}

Décompose ce raisonnement en étapes ordonnées selon les règles définies.
"""


BAREME_SYSTEM_PROMPT = """Tu arbitres la notation d'une question d'examen à partir du texte de barème rédigé par le professeur, et de la décomposition en étapes déjà produite pour cette même question.

Deux cas possibles, à distinguer toi-même :

CAS "DETAILED" — le texte rattache explicitement des montants de points à des critères identifiables parmi les 4 critères classiques (exactitude, cohérence, complétude, justification), même avec un vocabulaire différent (ex. "1pt si le calcul est juste" = exactitude). Dans ce cas, extrais le rattachement tel qu'il est écrit — ne réinterprète jamais un montant déjà explicitement attribué.

CAS "GLOBAL_PROPOSED" — le texte ne donne qu'un total global, sans détail par critère. Dans ce cas, PROPOSE une répartition plausible des points sur les 4 critères, en t'appuyant explicitement sur la décomposition fournie (nombre et nature des étapes, présence ou non d'une conclusion correcte, présence de justifications explicites dans le raisonnement, etc.) — JAMAIS une division mécanique du total par 4. Cette proposition ne sera jamais appliquée automatiquement : explique ton raisonnement.

Règle impérative : la somme des points par critère doit toujours être égale au total détecté.

Pour CHAQUE critère, classe aussi son mode de correction (correction_mode) — comment ce critère précis doit être vérifié, indépendamment des autres critères de la même question (deux critères d'une même question peuvent avoir des modes différents) :

- "solution_worked" : démarche précise, résultat déterminé (méthode et réponse attendues, vérifiables pas à pas).
- "criteria_based" : éléments/critères à citer ou démontrer, sans méthode unique imposée, sans réponse fixe.
- "multiple_distinct_answers" : plusieurs réponses différentes toutes valides, pas de démonstration à évaluer.
- "rubric_levels" : grille de niveaux qualitatifs (Excellent/Satisfaisant/Insuffisant), jugement global gradué.
- "binary_checklist" : rappel factuel, présence/absence, liste fermée d'items.
- "procedural_sequence" : l'ordre des étapes compte en lui-même (protocole, algorithme).
- "test_case_based" : validation par exécution (code). Signale uniquement ce mode ici — n'exécute rien, n'évalue aucun code.

Distinction impérative "criteria_based" vs "binary_checklist" : si un critère énumère PLUSIEURS éléments distincts à vérifier indépendamment pour un crédit partiel (ex. une liste de 2 ou plus faits/mentions/éléments attendus, même présentée sous forme de liste à tirets), c'est TOUJOURS "criteria_based" — jamais "binary_checklist", même si chaque élément de la liste se vérifie individuellement par présence/absence. "binary_checklist" est réservé à un critère qui se vérifie comme UN SEUL fait global, présent ou absent (ex. "le schéma est-il présent ?"), sans décomposition en sous-éléments notés séparément.

Il n'existe PAS de mode "jugement totalement libre sans aucun critère" — un tel cas n'existe pas en pratique. Si un critère semble échapper aux 6 autres modes, classe-le "criteria_based".

Règle impérative pour "criteria_based" : ne produis JAMAIS de réponse-modèle narrative (une phrase-exemple à laquelle comparer par ressemblance). Décompose le critère en conditions atomiques, chacune vérifiable indépendamment des autres (ex. "mentionne la relation causale entre X et Y", pas "l'élève doit expliquer que X entraîne Y de la façon suivante : ..."). Renseigne-les dans verifiable_conditions. Pour tout autre mode, verifiable_conditions doit être une liste vide.

Pour CHAQUE critère, indique aussi disqualifying (true/false) : true seulement si le texte indique explicitement que ce critère, s'il est violé, invalide la totalité des points de la question peu importe le reste (ex. "toute violation du protocole de sécurité annule la totalité de la note"). false dans tous les autres cas — ne le déduis jamais implicitement.

Règle impérative — QCM + justification : si la correction évalue à la fois un choix (QCM) et sa justification pour une même question, ce sont TOUJOURS deux critères séparés dans la liste criteria (ex. un critère "choix" et un critère "justification_choix" distincts) — ne les fusionne JAMAIS en un seul critère qui mélangerait les deux évaluations.

Pour un critère classé "test_case_based" (filières informatique), extrais en plus, si présents dans le texte :
- test_cases : liste de cas de test, chacun avec input, expected_output, et visibility ("visible" ou "hidden"). Si la visibilité n'est pas précisée explicitement pour un cas, utilise "visible" — ne devine JAMAIS "hidden" par défaut.
- reference_code : le code de référence du professeur, s'il en fournit un ; null sinon (la correction peut ne donner que des cas de test ou une spécification fonctionnelle, sans code).
- expected_complexity : la complexité algorithmique attendue, UNIQUEMENT si elle est explicitement mentionnée dans le texte (ex. "O(n log n)") ; null sinon — ne la déduis JAMAIS toi-même à partir d'un code.
Pour tout autre mode que "test_case_based", laisse ces trois champs à leur valeur vide (liste vide / null) — ils n'ont de sens que pour ce mode.

Pour un critère classé "rubric_levels", extrais en plus rubric_levels : la liste ORDONNÉE des niveaux tels que définis par le professeur dans le texte, du MEILLEUR niveau au PIRE (l'ordre reflète la hiérarchie ; aucun poids numérique n'est demandé ici). Chaque niveau porte "level" (le nom exact tel qu'écrit, ex. "Excellent") et "description" (le texte qui définit ce niveau, tel qu'écrit ou reformulé fidèlement, jamais résumé au point de perdre le sens). N'invente JAMAIS un niveau absent du texte, et ne complète JAMAIS une échelle standard (Excellent/Bon/Insuffisant) si le professeur en définit une différente ou n'en définit aucune explicitement — dans ce dernier cas, rubric_levels reste une liste vide.

Pour un critère classé "procedural_sequence", extrais en plus expected_steps : la liste ORDONNÉE des étapes attendues telles que décrites par le professeur (chaque étape en texte court, ex. "identifier les données", "appliquer la formule"). N'invente JAMAIS une étape absente du texte.

Pour tout autre mode que "rubric_levels"/"procedural_sequence" respectivement, laisse rubric_levels/expected_steps à liste vide — même garde-fou que test_cases/reference_code/expected_complexity ci-dessus.

Règle impérative — code fonctionnel vs qualité du code : si la correction évalue à la fois si le code fonctionne (tests, cas d'exécution) ET la qualité du code (style, lisibilité, bonnes pratiques), ce sont TOUJOURS deux critères séparés dans la liste criteria — le premier reste "test_case_based", le second est typiquement "rubric_levels" ou "criteria_based". Ne les fusionne JAMAIS en un seul critère qui mélangerait fonctionnement et style, exactement comme pour QCM + justification ci-dessus.

Règle impérative — règles générales (general_rules) : le texte de barème contient souvent, en plus des critères chiffrés, des éléments qui ne sont rattachés à AUCUN critère précis mais qui doivent influencer la correction dans son ensemble — règles communes, conditions d'application, consignes méthodologiques, exceptions, éléments obligatoires, ou toute indication sur la façon d'attribuer les points qui ne se limite pas à un seul critère. Recopie CHACUN de ces éléments tel quel (ou reformulé fidèlement, jamais résumé au point de perdre le sens) comme un item de la liste general_rules — jamais fondu dans un critère existant, jamais ignoré parce qu'il ne correspond à aucun des 4 critères classiques. Si le texte de barème n'en contient aucun, general_rules est une liste vide — ne l'invente jamais.

Format de réponse OBLIGATOIRE :
{
  "case": "DETAILED" | "GLOBAL_PROPOSED",
  "total_points": <float>,
  "criteria": [
    {
      "label": "exactitude",
      "points": <float>,
      "correction_mode": "solution_worked" | "criteria_based" | "multiple_distinct_answers" | "rubric_levels" | "binary_checklist" | "procedural_sequence" | "test_case_based",
      "verifiable_conditions": ["<condition atomique>", "..."],
      "disqualifying": false,
      "test_cases": [{"input": "<entrée>", "expected_output": "<sortie attendue>", "visibility": "visible" | "hidden"}],
      "reference_code": "<code de référence ou null>",
      "expected_complexity": "<complexité explicitement mentionnée, ex. 'O(n log n)', ou null>",
      "rubric_levels": [{"level": "<nom exact du niveau>", "description": "<description du niveau>"}],
      "expected_steps": ["<étape attendue>", "..."]
    }
  ],
  "general_rules": ["<règle générale non rattachée à un critère précis>", "..."],
  "justification": "<raisonnement, obligatoire surtout pour GLOBAL_PROPOSED>"
}
"""

BAREME_USER_TEMPLATE = """Texte de barème de la correction (question : {statement}) :
{bareme_text}

Décomposition déjà produite pour cette question (à utiliser pour CAS "GLOBAL_PROPOSED") :
{decomposition_summary}

Détermine le cas applicable et produis le résultat selon les règles définies.
"""


# Cas 0 (prioritaire sur Cas 1/2/3 ci-dessus, chantier barème C2PCT natif) —
# UN SEUL appel pour TOUT l'exercice (jamais par question, contrairement à
# DECOMPOSITION_*/BAREME_* ci-dessus) : le professeur peut donner des points
# directement par sous-question C2PCT, regroupés n'importe où dans le
# document (souvent une section barème dédiée, à la fin ou au début, jamais
# forcément adjacente à chaque question) — le texte source transmis ici est
# donc le document ENTIER (toutes les questions concaténées), pas le texte
# d'une seule question. Reste distinct du barème classique Cas 1/2/3
# (4 critères exactitude/cohérence/complétude/justification, ci-dessus) :
# les deux mécanismes coexistent, celui-ci alimente uniquement la répartition
# du barème ENTRE COMPÉTENCES C2PCT (Pedagogical_Evaluation_Agent), jamais le
# correction_mode par critère.
SUBQUESTION_POINTS_SYSTEM_PROMPT = """Tu cherches, dans un document de correction d'examen complet (plusieurs questions), une éventuelle section de barème qui donne des points DIRECTEMENT par sous-question officielle C2PCT (identifiée par une numérotation explicite comme "1.1", "3.1", ou par une correspondance claire avec l'intention de la sous-question) — PAS par les 4 critères classiques (exactitude/cohérence/complétude/justification), qui sont un mécanisme totalement différent et hors de ta tâche ici.

Ce barème détaillé peut être placé N'IMPORTE OÙ dans le document : dispersé juste après chaque question, ou regroupé en une seule section dédiée (au début ou à la fin du document). Balaye l'INTÉGRALITÉ du texte fourni, jamais seulement son début ou sa fin.

Format typique d'une section regroupée (illustratif, la mise en forme réelle peut varier) :
BARÈME
1) 1.1 → 2 points
   1.2 → 1 point
   1.4 → 1 point
2) 3.1 → 2 points
5) → 1 point

Dans cet exemple, "1)", "2)", "5)" sont des numéros de question (à faire correspondre à l'ordre des questions listé dans le message utilisateur), et chaque ligne en dessous associe une sous-question C2PCT à ses points. Une question peut n'avoir AUCUNE sous-question C2PCT chiffrée (ex. "5) → 1 point" dans l'exemple : un total sans détail par sous-question) — dans ce cas, n'associe RIEN à cette question ici, son barème sera traité par le mécanisme classique ailleurs.

RÈGLES STRICTES :
1. N'associe des points à une sous-question QUE si le rattachement est EXPLICITE et NON AMBIGU dans le texte — jamais une déduction, jamais une répartition que tu inventerais toi-même. Si aucune section de ce type n'existe dans le document, renvoie une liste "questions" vide.
2. Une sous-question doit être identifiable parmi les 15 sous-questions officielles listées à la toute fin de ce message — n'invente JAMAIS un id hors de cette liste.
3. Ignore complètement tout texte relatif au barème classique par critères (exactitude/cohérence/complétude/justification) — ce n'est pas ta tâche ici.
4. Si un même numéro de question apparaît associé à un total global SANS détail par sous-question, ne produis aucune entrée subquestion_points pour cette question (liste/dict vide ou question absente du résultat).

Règle impérative — règles générales (general_rules) : ce document peut aussi contenir des règles communes/consignes qui ne sont rattachées à aucune sous-question précise mais qui doivent influencer la correction dans son ensemble (ex. mention explicite que la méthodologie C2PCT doit être suivie, condition d'application générale, pénalité non chiffrée, élément obligatoire...). Recopie CHACUNE telle quelle (ou reformulée fidèlement) dans general_rules — portée DOCUMENT ENTIER, pas par question. Liste vide si aucune n'est présente, jamais inventée.

Format de réponse OBLIGATOIRE :
{
  "questions": [
    {
      "question_order": 1,
      "subquestion_points": {"1.1": 2, "1.2": 1, "1.4": 1}
    }
  ],
  "general_rules": ["<règle générale du barème C2PCT non rattachée à une sous-question précise>", "..."]
}
"""

SUBQUESTION_POINTS_USER_TEMPLATE = """Numéros de question existant réellement dans cet exercice (n'utilise jamais un numéro hors de cette liste) : {question_orders}

Document complet (toutes les questions et leurs corrections, concaténées) :
{full_document_text}

Cherche une section de barème détaillé par sous-question C2PCT dans L'INTÉGRALITÉ de ce texte, selon les règles définies. Si aucune section de ce type n'existe, renvoie {{"questions": []}}.
"""


# ---------------------------------------------------------------------------
# 4. Segmentation par sous-question (SUBQUESTION_SEGMENTATION_*, 2026-08-29,
#    backlog_bugs_c2pct.md, structuration Question.subquestions) — appel
#    LLM SÉPARÉ et DÉDIÉ, exécuté UNIQUEMENT si covered_subquestions (déjà
#    produit par l'appel de décomposition ci-dessus) est non vide pour cette
#    question. Ne redemande JAMAIS quels ids sont couverts (déjà tranché) —
#    son seul travail : localiser, pour CHAQUE id déjà confirmé, l'extrait
#    VERBATIM (citation exacte, jamais une paraphrase/un résumé) du texte
#    source correspondant. Volontairement séparé de l'appel de décomposition
#    (jamais ajouté à son schéma) : cet appel fait déjà beaucoup, et cette
#    session a déjà vu un cas réel (Solution_Variant_Generation_Agent) où un
#    seul appel LLM chargé de trop de tâches à la fois perd en fiabilité sur
#    l'une d'elles.
#
#    Garde-fou déterministe OBLIGATOIRE côté code (jamais suffisant côté
#    prompt seul) : chaque `content` retourné est vérifié comme extrait RÉEL
#    du texte source (tolérance UNIQUEMENT sur espaces/casse, cf.
#    ExtractionVerificationAgent._find_verbatim_span) avant d'être persisté
#    — un segment non retrouvé est rejeté, jamais persisté tel quel.
# ---------------------------------------------------------------------------

SUBQUESTION_SEGMENTATION_SYSTEM_PROMPT = """Tu extrais, pour une liste de sous-questions C2PCT DÉJÀ CONFIRMÉES comme couvertes, l'extrait de texte EXACT (citation verbatim) qui y répond dans le texte source fourni.

RÈGLES STRICTES :
1. CITATION EXACTE UNIQUEMENT — recopie le texte tel qu'il apparaît dans la source, caractère pour caractère (les seules tolérances acceptées à la vérification qui suit sont les espaces/retours à la ligne et la casse — jamais reformuler, résumer, corriger une faute, ou compléter). Si tu ne peux pas citer exactement, n'inclus PAS cette sous-question dans ta réponse plutôt que d'approximer.
2. Une sous-question par entrée, pour CHAQUE id de la liste fournie (jamais un id hors de cette liste, jamais un id de cette liste ignoré si tu peux localiser son texte).
3. Inclus tout le texte pertinent à cette sous-question précise (la question posée ET sa réponse si présentes ensemble), mais n'inclus JAMAIS le texte d'une AUTRE sous-question — les frontières doivent être nettes.
4. Le texte source répète souvent l'énoncé du problème en en-tête de chaque bloc (bruit de mise en page) — ne l'inclus pas dans l'extrait sauf s'il fait partie intégrante de la réponse.

Format de réponse OBLIGATOIRE :
{
  "segments": [
    {"id": "1.1", "content": "<extrait exact du texte source>"}
  ]
}
"""

SUBQUESTION_SEGMENTATION_USER_TEMPLATE = """Sous-questions déjà confirmées comme couvertes pour cette question (extrais UNIQUEMENT celles-ci, id par id) : {covered_ids}

### Énoncé :
{statement}

### Correction :
{correction_text}

Pour chaque id ci-dessus, cite l'extrait exact du texte source (énoncé ou correction) qui y répond.
Réponds exclusivement par l'objet JSON spécifié.
"""
