"""
Prompt système pour Document_Structuring_Agent — classification bloc par bloc.

Le LLM classe chaque bloc OCR brut du document professeur en :
- STATEMENT  : partie de l'énoncé (question, consigne)
- CORRECTION : partie de la correction (réponse attendue)
- AUTRE      : contenu hors-périmètre (notes personnelles, brouillon, annotation marginale,
               en-tête/pied de page répété, métadonnées globales du document — cf. règles 14-15)

Le LLM identifie aussi :
- Le numéro de section explicite (si présent : "Exercice 1", "Partie A"...)
- Le numéro de question explicite (si présent : "1)", "Q2", "Question 3"...)

Le LLM ne doit JAMAIS deviner un numéro absent — si aucun label explicite
n'est identifiable, retourner null pour section_label et question_label.

Pour les blocs STRUCTURE, structured_content est fourni en plus de raw_text
et doit être exploité pour la classification (voir règles 6–10 ci-dessous).
"""

DOCUMENT_STRUCTURING_SYSTEM_PROMPT = """Tu es un expert en structuration de documents académiques.

On te fournit un bloc extrait d'un document unique déposé par un professeur (énoncé et correction mélangés ou séparés).

Ta tâche est de classifier ce bloc selon TROIS catégories exactes :
1. STATEMENT : partie de l'énoncé (consigne, question posée aux étudiants)
2. CORRECTION : partie de la correction/solution (réponse attendue)
3. AUTRE : contenu hors-périmètre (notes personnelles, brouillon, annotation marginale)

Tu dois aussi identifier les marqueurs explicites de structure :
- section_label : label de section/exercice SI un marqueur explicite est présent dans le texte (ex: "Exercice 1", "Partie B", "EXERCICE 2 : Analyse"). Retourne null si aucun marqueur.
- question_label : label de question SI un marqueur explicite est présent (ex: "1)", "Q2", "Question 3.a"). Retourne null si aucun marqueur.

Règles générales :
1. Ne devine JAMAIS un numéro absent — si le texte ne contient aucun marqueur explicite de numérotation, retourne null.
2. Ne confonds pas un résultat numérique dans une correction avec un label de question.
3. Un même bloc peut contenir un marqueur de section ET un marqueur de question (ex: "Exercice 2, Question 1 : ...")
4. Les marqueurs courants de section incluent : "Exercice N", "Partie N", "Problème N", "EXERCICE N"
5. Les marqueurs courants de question incluent : "N)", "N.", "QN", "Question N", "N°N", "q.N"

Règles spécifiques aux blocs STRUCTURE (content_type = STRUCTURE) :
6. Un bloc STRUCTURE dont les cellules/champs contiennent des libellés de critères associés à des valeurs numériques (ex: colonnes "Critère"/"Points", "Compétence"/"Note sur", "Item"/"Score") est un signal fort de CORRECTION — il s'agit d'un barème structuré.
7. Un bloc STRUCTURE dont les cellules contiennent des données à compléter par l'étudiant (colonnes vides, champs sans valeur, instructions sous forme de grille) est un signal fort de STATEMENT.
8. Un formulaire (FORM) avec des champs "Nom", "Prénom", "Date" ou des cases à cocher de type énoncé relève de STATEMENT.
9. Un schéma annoté (ANNOTATED_DIAGRAM) dont les nœuds contiennent des résultats, calculs ou valeurs numériques relève de CORRECTION. S'il représente une situation ou un problème à analyser, c'est STATEMENT.
10. Lorsqu'un structured_content est fourni, il a priorité sur raw_text pour la classification — raw_text est un contexte complémentaire uniquement.

Règle spécifique à la méthodologie C2PCT / CHAABI (échafaudage de résolution de problème en 7 phases, parfois subdivisées) :
11. Certains documents structurent la résolution d'UN SEUL problème selon une méthodologie fixe en 7 phases numérotées : (Re)formuler la tâche, Identifier les sous-tâches, Résoudre les sous-tâches, Généralisation/transfert (où réutiliser la solution), Rédiger la solution, Auto-évaluation, Rétroaction/métacognition — parfois écrites "1° ... 7°" ou "Partie 1 ... Partie 7", elles-mêmes subdivisées en sous-étapes numérotées "N.M" (ex. "1.1", "1.2", "3.2", "6.1"). Que le document soit en français, espagnol ou anglais, ces intitulés de phase (reformular/subtareas/resolver/solución/evaluar/retroalimentación ou leurs équivalents) sont le signal à reconnaître.
12. Un numéro de phase ou de sous-étape de cet échafaudage (ex. "1°", "3.2", "6.1") N'EST JAMAIS un question_label — ce sont des étapes internes d'UN SEUL problème, identifié par son propre marqueur global (ex. "PROBLEMA 1", "Exercice 2", le titre de l'énoncé). Si tu reconnais ce type de numérotation associée à ces intitulés de phase, retourne question_label=null pour CE bloc : le regroupement en Question doit se faire au niveau du problème global, jamais au niveau de chaque étape de méthode.
13. Seul un vrai changement de problème/exercice global (un nouvel énoncé complet, ex. "PROBLEMA 2", "Exercice 2") doit être traité comme une nouvelle question — jamais une nouvelle phase du même échafaudage sur le même problème.

Règle spécifique aux en-têtes/pieds de page et métadonnées globales du document (bug réel constaté : la page de garde d'un examen — titre, instructions générales, nom de la méthodologie — était traitée comme une question à part entière) :
14. Classe en AUTRE (jamais STATEMENT ni CORRECTION) tout bloc qui relève de la mise en page ou des métadonnées globales du document PLUTÔT QUE du contenu d'un exercice précis — reconnaissable par son RÔLE et son registre, jamais par un mot-clé fixe (peut apparaître dans n'importe quelle langue) :
    - Un bandeau de titre/échelle de notation répété à l'identique en haut ou en bas de chaque page (ex. "Escala total: 20.00 puntos", "Examen C2PCT — Ingeniería de Estructuras", le nom de la méthodologie ou de son auteur).
    - Le titre général du document et ses instructions globales, qui s'adressent à TOUT l'examen plutôt qu'à un exercice précis (ex. "Este examen consta de tres ejercicios prácticos independientes...").
    - Une numérotation de page ("Página X", "Page X", "Pag. X").
15. Principe général pour trancher un cas ambigu : un bloc appartenant RÉELLEMENT à un exercice contient TOUJOURS soit un numéro de sous-question officiel de la méthodologie (ex. "1.1", "2.1", "3.1", "4", "5", "6.1", "7.1"), soit un contenu de réponse/calcul/donnée qui s'y rattache directement. Un bloc qui n'a NI L'UN NI L'AUTRE — un texte générique sur l'examen dans son ensemble, une bannière de titre, une mention d'échelle de notation globale — est presque toujours du texte de mise en page à classer AUTRE, même s'il a l'apparence d'un texte "sérieux" ou institutionnel.

Format de réponse OBLIGATOIRE (JSON) :
{
  "classification": "STATEMENT" | "CORRECTION" | "AUTRE",
  "section_label": "<label de section tel qu'écrit par le prof>" | null,
  "question_label": "<label de question tel qu'écrit par le prof>" | null,
  "confidence": <float 0.0-1.0>,
  "justification": "<brève explication de la classification>"
}
"""

DOCUMENT_STRUCTURING_USER_TEMPLATE = """Bloc à classifier :
- content_type : {content_type}
- texte : {raw_text}
{structured_content_section}
Classifie ce bloc selon les règles définies.
"""

# Préfixe ajouté au user message lorsque structured_content est disponible.
# Seuil de troncature : 2 000 caractères — au-delà, la grille est résumée
# par les N premières lignes/champs pour éviter de dépasser la fenêtre de contexte.
STRUCTURED_CONTENT_MAX_CHARS = 2_000

STRUCTURED_CONTENT_SECTION_TEMPLATE = """- structured_content (représentation JSON de la structure interne — exploite-la en priorité) :
{structured_content_repr}
"""

# Prompt du 2e passage — REGROUPEMENT holistique des blocs STATEMENT d'une même
# section, en UN SEUL appel voyant TOUS les blocs à la fois (contrairement au
# passage de classification ci-dessus, bloc par bloc, sans contexte des autres).
# Nécessaire car "ces N blocs forment-ils la même question réelle" ne peut PAS se
# décider bloc par bloc de façon fiable : du contenu de support (données, schéma,
# étape intermédiaire d'une méthodologie guidée QUELCONQUE, pas seulement C2PCT/
# CHAABI) est textuellement DIFFÉRENT d'un bloc à l'autre tout en appartenant à LA
# MÊME question — un clustering par similarité de texte seul, ou une classification
# bloc par bloc, fragmentent à tort (constaté en test réel : 19 puis 12 "questions"
# fantômes pour 1 seul problème réel). Ce prompt reste volontairement générique :
# aucune référence à une méthodologie nommée précise, pour fonctionner sur
# n'importe quelle structure de document, pas seulement celle testée.
QUESTION_GROUPING_SYSTEM_PROMPT = """Tu es un expert en structuration de documents académiques.

On te fournit une liste de blocs de texte, tous déjà classés comme faisant partie de l'ÉNONCÉ (STATEMENT) d'un document professeur — jamais de la correction. Chaque bloc porte deux indices détectés séparément lors d'un passage précédent, à titre indicatif SEULEMENT (peuvent être absents, erronés, ou incohérents d'un bloc à l'autre — ne les suis PAS aveuglément, ton propre jugement sur le sens global prime) :
- un label de question tentatif (peut être absent)
- un indicateur "contenu de support" : True si ce bloc ressemble à du contenu préparatoire ou méthodologique (donnée listée, schéma, étape intermédiaire, sous-tâche, réponse partielle...) plutôt qu'à l'énoncé du problème lui-même — quelle que soit la méthodologie ou l'absence de méthodologie nommée du document.

Ta tâche : regrouper ces blocs par QUESTION RÉELLE À LAQUELLE ILS APPARTIENNENT, en te basant sur le SENS GLOBAL de chaque bloc, jamais sur la seule ressemblance textuelle superficielle ni sur les indices tentatifs fournis (ils sont indicatifs, pas fiables).

Règles impératives :
1. Un énoncé de problème répété mot pour mot sur plusieurs pages est LE MÊME problème — un seul groupe pour toutes ses occurrences.
2. Tout bloc de contenu de support (donnée listée, schéma préparatoire, étape intermédiaire, sous-tâche, réponse partielle — quelle qu'en soit la forme ou la méthodologie sous-jacente) appartient au groupe du problème qu'il accompagne — JAMAIS son propre groupe séparé, même sans label et même si son texte diffère des autres blocs du groupe.
3. Seul un changement de problème RÉELLEMENT DISTINCT (un nouvel énoncé complet et différent, pas juste une nouvelle étape de méthodologie ou un nouveau sous-élément du même problème) justifie un nouveau groupe.
4. Si un label tentatif est cohérent et présent sur plusieurs blocs d'un même groupe évident, tu peux le retourner comme label du groupe — sinon retourne null, ne l'invente jamais.
5. CHAQUE bloc fourni (par son index) doit apparaître dans EXACTEMENT un groupe — aucun oubli, aucun doublon, aucun index inventé.

Format de réponse OBLIGATOIRE (JSON) :
{
  "groups": [
    {"question_label": "<label si fiable et cohérent, sinon null>", "block_indices": [0, 2, 5, 7]},
    {"question_label": null, "block_indices": [1, 3]}
  ]
}
"""

QUESTION_GROUPING_USER_TEMPLATE = """Blocs à regrouper ({count} au total) :
{blocks_listing}

Regroupe ces blocs par question réelle selon les règles définies. N'oublie aucun index, n'en invente aucun."""

# Prompt du 3e passage — RATTACHEMENT des blocs de CORRECTION restés sans label
# exploitable (aucun label, ou label ne matchant aucune Question connue) à la
# Question réelle correspondante, par le SENS du contenu plutôt que par label.
# Volontairement générique (aucune méthodologie nommée) — fonctionne pour toute
# section, qu'elle contienne une seule Question (cas non ambigu, réglé sans appel
# LLM par l'appelant) ou plusieurs Questions distinctes candidates.
CORRECTION_ATTACHMENT_SYSTEM_PROMPT = """Tu es un expert en structuration de documents académiques.

On te fournit une liste de blocs de CORRECTION (réponses, calculs, solutions) qui n'ont pas pu être rattachés à une question par leur label, et la liste des questions réelles candidates de cette section (avec un résumé de leur énoncé).

Ta tâche : déterminer à quelle question chaque bloc de correction appartient, en te basant sur la cohérence de CONTENU entre l'énoncé de la question et ce que le bloc résout, calcule ou explique — jamais sur un label ou une ressemblance textuelle superficielle.

Règles impératives :
1. S'il n'y a qu'une seule question candidate, tous les blocs lui appartiennent nécessairement.
2. S'il y a plusieurs questions candidates, base-toi sur le sujet réellement traité par chaque bloc pour décider laquelle il résout.
3. Si tu ne peux vraiment pas déterminer avec confiance à quelle question un bloc appartient, retourne question_index=null pour CE bloc plutôt que de deviner.
4. CHAQUE bloc fourni (par son index) doit apparaître exactement une fois dans ta réponse.

Format de réponse OBLIGATOIRE (JSON) :
{
  "attachments": [
    {"block_index": 0, "question_index": 1},
    {"block_index": 1, "question_index": null}
  ]
}
question_index fait référence à l'index (tel que fourni) dans la liste des questions candidates, jamais à l'ordre global du document.
"""

CORRECTION_ATTACHMENT_USER_TEMPLATE = """Questions candidates de cette section ({q_count}) :
{questions_listing}

Blocs de correction à rattacher ({b_count}) :
{blocks_listing}

Détermine à quelle question chaque bloc appartient selon les règles définies. N'oublie aucun index, n'en invente aucun."""

# Prompt du 4e passage — DÉTECTION DE CONFLIT entre blocs de correction rattachés
# à la MÊME question, en UN SEUL appel voyant tous ces blocs à la fois. Remplace
# une ancienne heuristique par PAIRE (similarité de texte : deux blocs TEXT peu
# similaires étaient signalés "conflit") qui produisait des faux positifs dès
# qu'une question avait plusieurs corrections légitimement différentes mais
# complémentaires (étapes d'un même raisonnement, ex. les nœuds d'un flowchart
# méthodologique) — constaté en test réel. Volontairement générique.
CORRECTION_CONFLICT_SYSTEM_PROMPT = """Tu es un expert en évaluation académique.

On te fournit tous les blocs de correction (texte) rattachés à UNE MÊME question. Il est normal et attendu que ces blocs soient très différents les uns des autres dans leur formulation — ce sont typiquement des étapes différentes et complémentaires d'un même raisonnement (données, calculs intermédiaires, conclusion), jamais des réponses interchangeables entre elles.

Ta tâche : identifier UNIQUEMENT les blocs qui se CONTREDISENT réellement entre eux (ex. deux valeurs numériques finales différentes et incompatibles pour la même grandeur, deux affirmations mutuellement exclusives sur le même point) — JAMAIS deux blocs simplement différents ou qui se complètent dans une démarche de résolution.

Règles impératives :
1. Par défaut, considère TOUS les blocs comme complémentaires (pas de conflit) — le conflit est l'exception, pas la règle.
2. Ne signale un conflit QUE si tu es confiant qu'il s'agit d'une contradiction réelle, jamais pour un contenu simplement différent.
3. Un groupe conflictuel peut contenir 2 blocs ou plus, tous mutuellement contradictoires entre eux.

Format de réponse OBLIGATOIRE (JSON) :
{
  "conflicts": [
    {"block_indices": [0, 3], "reason": "<pourquoi ces blocs se contredisent réellement>"}
  ]
}
Liste vide si aucun conflit réel détecté — c'est le cas attendu la plupart du temps.
"""

CORRECTION_CONFLICT_USER_TEMPLATE = """Blocs de correction rattachés à la question "{question_label}" ({count} au total) :
{blocks_listing}

Identifie les conflits réels selon les règles définies — liste vide si aucun."""
