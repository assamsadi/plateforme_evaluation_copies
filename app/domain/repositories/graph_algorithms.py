"""
Algorithmes de théorie des graphes, purs (aucune dépendance DB/ORM) —
séparés des repositories pour rester testables isolément (Single
Responsibility : un repository fait de l'accès aux données, pas de la
théorie des graphes).

Algorithme de Kahn retenu plutôt que DFS pour le tri topologique (§
discussion) : détecte un cycle EN MÊME TEMPS qu'il produit l'ordre, en
une seule passe — une fonction fait les deux, pas besoin de deux
algorithmes séparés comme le ferait un DFS classique (marquage
in_progress/visited) suivi d'un tri distinct.
"""
from collections import deque


class CyclicGraphError(Exception):
    """
    Levée si le graphe contient un cycle — ne devrait JAMAIS se produire
    en usage normal (la validation Pydantic amont, cf.
    solution_schemas.SolutionVariantCreate._check_no_cycle, empêche déjà
    la création d'un graphe cyclique). Si cette exception remonte, c'est
    le signe d'un bug ailleurs (contournement de la validation amont,
    modification directe en DB, etc.) — fail loud plutôt qu'un flag
    silencieux que l'appelant pourrait oublier de vérifier.
    """
    def __init__(self, remaining_nodes: set[str]) -> None:
        self.remaining_nodes = remaining_nodes
        super().__init__(
            f"Cycle détecté dans le graphe : les nœuds {remaining_nodes} "
            f"n'ont pas pu être ordonnés (dépendance circulaire)"
        )


def topological_sort(graph: dict[str, list[str]]) -> list[str]:
    """
    Algorithme de Kahn, O(V + E).

    `graph` : dict {node_id: [node_ids dont ce nœud DÉPEND]}, ex.
        {"step3": ["step1", "step2"], "step1": [], "step2": []}
        signifie step3 dépend de step1 ET step2.

    Retourne l'ordre topologique (les nœuds sans dépendance en premier).
    Lève CyclicGraphError si un cycle empêche d'ordonner tous les nœuds.
    """
    # in_degree[n] = nombre de nœuds qui dépendent de n ET pas encore traités
    # On inverse la lecture : graph[n] = dépendances de n, donc l'arête
    # va de chaque dépendance VERS n. in_degree[n] = len(graph[n]).
    all_nodes = set(graph.keys())
    for deps in graph.values():
        all_nodes.update(deps)

    in_degree: dict[str, int] = {node: 0 for node in all_nodes}
    adjacency: dict[str, list[str]] = {node: [] for node in all_nodes}  # dep -> [nœuds qui en dépendent]

    for node, deps in graph.items():
        in_degree[node] = len(deps)
        for dep in deps:
            adjacency[dep].append(node)

    queue: deque[str] = deque(n for n in all_nodes if in_degree[n] == 0)
    ordered: list[str] = []

    while queue:
        node = queue.popleft()
        ordered.append(node)
        for dependent in adjacency[node]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(ordered) != len(all_nodes):
        remaining = all_nodes - set(ordered)
        raise CyclicGraphError(remaining)

    return ordered