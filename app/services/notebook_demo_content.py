"""
Contenu de démonstration pour les notebooks marqués "demo-notebook-" (captures
d'écran / soutenance) : cartes mémoire et réponses de chat, sans appel à
NotebookLM. Jamais utilisé pour un vrai notebook (notebook_id d'origine Google).
"""
import base64
import json

DEMO_NOTEBOOK_PREFIX = "demo-notebook-"

_FLASHCARDS = {
    "algorithmic_structuring": {
        "title": "Structuration algorithmique — cartes de révision",
        "cards": [
            {"front": "Que décrit la sous-question 3.1 de la méthode C2PCT ?", "back": "Les étapes de résolution du problème, écrites avec ses propres mots."},
            {"front": "Pourquoi représenter les étapes par un schéma (sous-question 3.2) ?", "back": "Pour rendre l'ordre et les dépendances entre étapes visibles avant de calculer."},
            {"front": "Dans quel ordre décrire les étapes d'un algorithme de parcours de graphe (BFS) ?", "back": "Initialiser la file, marquer le sommet de départ, puis défiler, visiter les voisins non marqués et les enfiler."},
            {"front": "Quelle est la différence entre une étape et un résultat intermédiaire ?", "back": "Une étape est une action à effectuer ; un résultat intermédiaire est la valeur qu'elle produit."},
            {"front": "Comment vérifier qu'une suite d'étapes est complète ?", "back": "En la rejouant sur un petit exemple et en contrôlant que chaque donnée nécessaire est produite avant d'être utilisée."},
            {"front": "Complexité du parcours en largeur (BFS) sur un graphe de n sommets et m arêtes ?", "back": "O(n + m)."},
            {"front": "Pourquoi une table de hachage donne-t-elle des accès en O(1) en moyenne ?", "back": "La fonction de hachage calcule directement l'indice du seau ; les collisions sont rares si la table est bien dimensionnée."},
            {"front": "Nommer deux stratégies de gestion des collisions.", "back": "Le chaînage (une liste par seau) et l'adressage ouvert (sondage linéaire ou quadratique)."},
        ],
    },
    "reflection_and_metacognition": {
        "title": "Réflexion et métacognition — cartes de révision",
        "cards": [
            {"front": "Que demandent les sous-questions 7.1 et 7.2 de la méthode C2PCT ?", "back": "Les difficultés rencontrées pour comprendre le problème, et l'utilité de la structure suivie."},
            {"front": "Pourquoi expliciter ses difficultés après un exercice ?", "back": "Cela permet d'identifier ce qui bloque et de choisir quoi retravailler en priorité."},
            {"front": "Comment repérer une étape de raisonnement où l'on a hésité ?", "back": "En relisant sa copie et en notant chaque endroit où l'on a corrigé, barré ou refait un calcul."},
            {"front": "Que peut-on écrire pour la sous-question 7.2 ?", "back": "Une phrase sur ce que la structure en 7 phases a rendu plus facile ou plus long."},
            {"front": "Quelle question se poser avant de rendre sa copie ?", "back": "Mon résultat est-il vraisemblable, et ai-je répondu à la question posée ?"},
            {"front": "Comment transformer une erreur en progrès ?", "back": "Identifier sa cause, la reformuler avec ses mots, puis refaire un exercice court qui la teste."},
        ],
    },
}
_FLASHCARDS_DEFAULT = {
    "title": "Cartes de révision",
    "cards": [
        {"front": "Que mesure le profil de compétences C2PCT ?", "back": "Le niveau de maîtrise de l'étudiant sur 7 compétences, calculé à partir de ses copies corrigées."},
        {"front": "Pourquoi le niveau de maîtrise tient-il plus compte des copies récentes ?", "back": "Une décroissance exponentielle pondère chaque copie : les plus récentes pèsent davantage, sans effacer les anciennes."},
        {"front": "Quand une faiblesse est-elle dite persistante ?", "back": "Quand les trois dernières copies sont toutes sous le seuil de 50 %."},
    ],
}

_ANSWERS = [
    (("étape", "etape", "ordre", "décrire", "decrire"),
     "Pour structurer ta démarche, commence par écrire 4 à 6 étapes en phrases courtes, avant tout calcul ou diagramme. "
     "Vérifie ensuite que chaque étape utilise uniquement des données déjà produites par les étapes précédentes. "
     "Dans ta dernière copie, quelle étape dépendait d'un résultat que tu n'avais pas encore calculé ?"),
    (("schéma", "schema", "diagramme", "dessin"),
     "Un bon schéma reprend exactement tes étapes écrites : une boîte par étape, une flèche par dépendance. "
     "C'est ce qui manquait à ta copie sur la sous-question 3.2. Peux-tu essayer de dessiner le parcours en largeur d'un petit graphe de 5 sommets ?"),
    (("complexité", "complexite", "o(", "coût", "cout"),
     "Pour la complexité, compte d'abord les opérations élémentaires par itération, puis multiplie par le nombre d'itérations. "
     "Pour un parcours de graphe, chaque sommet et chaque arête sont traités une seule fois : que te donne cela comme ordre de grandeur ?"),
    (("hachage", "collision", "table"),
     "Une table de hachage range chaque clé dans un seau calculé par une fonction de hachage. Quand deux clés arrivent dans le même seau, on parle de collision. "
     "Connais-tu la différence entre le chaînage et l'adressage ouvert pour les résoudre ?"),
    (("difficulté", "difficulte", "bloqu", "comprends pas", "comprendre"),
     "Identifier précisément ce qui te bloque est déjà un progrès. Relis l'énoncé et souligne les données, puis ce qui est demandé : "
     "à quel moment ta compréhension s'arrête-t-elle ? C'est ce point que nous allons travailler ensemble."),
]
_ANSWER_DEFAULT = (
    "D'après ton profil de compétences et ton dernier retour, le point à consolider en priorité est la façon dont tu enchaînes tes étapes de résolution. "
    "Peux-tu reformuler la question avec tes mots, en précisant l'exercice sur lequel tu travailles ?"
)


def is_demo_notebook(notebook_id: str | None) -> bool:
    return bool(notebook_id) and notebook_id.startswith(DEMO_NOTEBOOK_PREFIX)


def flashcards_data_url(competency_code: object) -> str:
    key = str(getattr(competency_code, "value", competency_code)).lower()
    payload = json.dumps(_FLASHCARDS.get(key, _FLASHCARDS_DEFAULT), ensure_ascii=False).encode("utf-8")
    return "data:application/json;base64," + base64.b64encode(payload).decode("ascii")


def chat_answer(question: str) -> str:
    q = question.lower()
    for keywords, answer in _ANSWERS:
        if any(k in q for k in keywords):
            return answer
    return _ANSWER_DEFAULT
