"""
Tests unitaires pour Solution_Variant_Generation_Agent :
- _verify_intermediate_consistency (aucun appel LLM, couche sympy pure)
- _resolve_symbol_correspondences (v1.9, correspondance sémantique LLM entre
  symboles au nommage différent — ex. "N" générique vs "N_5" spécialisé)
"""
import pytest

import app.agents.Solution_Variant_Generation_Agent as svga_module
from app.agents.Solution_Variant_Generation_Agent import (
    SolutionVariantGenerationAgent,
    _SymbolCorrespondenceEntrySchema,
    _SymbolCorrespondenceSchema,
)
from app.domain.schemas.solution_variant_generation_schemas import (
    CandidateStepSummarySchema,
    ReferenceStepContext,
)

agent = SolutionVariantGenerationAgent()


# ---------------------------------------------------------------------------
# _verify_intermediate_consistency (sync, sympy pur)
# ---------------------------------------------------------------------------

def test_shared_symbol_matching_values_is_verified_consistent():
    """Même symbole des deux côtés, même valeur -> réellement vérifié, pas seulement 'pas de conflit'."""
    ref_steps = [ReferenceStepContext(formula="N_5 = 3*P*sqrt(5)", description="Effort dans la barre 5.")]
    cand_steps = [
        CandidateStepSummarySchema(order=1, step_type="computation", description="d", formula="N_5 = 3*P*sqrt(5)"),
    ]
    is_consistent, conflicts, verified_count, ambiguous = agent._verify_intermediate_consistency(ref_steps, cand_steps)
    assert is_consistent is True
    assert conflicts == []
    assert verified_count == 1, "une comparaison reelle a eu lieu, verified_count doit le refleter"
    assert ambiguous == []


def test_shared_symbol_with_disagreeing_value_is_rejected():
    """Même symbole des deux côtés, valeurs différentes -> vrai conflit détecté (non-régression v1.5)."""
    ref_steps = [ReferenceStepContext(formula="N_5 = 3*P*sqrt(5)", description="d")]
    cand_steps = [
        CandidateStepSummarySchema(order=1, step_type="computation", description="d", formula="N_5 = 2*P"),
    ]
    is_consistent, conflicts, verified_count, ambiguous = agent._verify_intermediate_consistency(ref_steps, cand_steps)
    assert is_consistent is False
    assert len(conflicts) == 1
    assert verified_count == 1
    assert ambiguous == []


def test_generic_vs_specialized_symbol_is_ambiguous_not_verified_not_a_conflict():
    """
    Bug reel du 2026-08-17 (Face 1, corrige en v1.8) : reference utilise un
    symbole GENERIQUE (N, jamais resolu ailleurs dans la reference) tandis
    que le candidat nomme la meme grandeur physique de facon SPECIALISEE
    (N_5). Ne doit jamais etre traite comme un conflit ni comme une
    confirmation par la couche sympy seule -- doit ressortir comme une paire
    AMBIGUE (Face 2, resolue par _resolve_symbol_correspondences si un LLM
    est disponible).
    """
    ref_steps = [
        ReferenceStepContext(
            formula=r"\sigma_{max} = \frac{N}{A} \cdot \omega",
            description="Contrainte maximale generale, N = effort dans la barre consideree.",
        ),
        ReferenceStepContext(
            formula=r"\sigma_5 = \frac{3P\sqrt{5} \cdot 10^3}{\frac{\pi \cdot 30^2}{4}}",
            description="Contrainte specifique de la barre 5, la barre critique.",
        ),
    ]
    cand_steps = [
        CandidateStepSummarySchema(
            order=1, step_type="given_data", description="Effort axial dans la barre critique 5.",
            formula=r"N_5 = 3P\sqrt{5}",
        ),
        CandidateStepSummarySchema(
            order=2, step_type="computation", description="Contrainte maximale.",
            formula=r"\sigma_{max} = \frac{N_5}{A} \cdot \omega",
        ),
    ]
    is_consistent, conflicts, verified_count, ambiguous = agent._verify_intermediate_consistency(ref_steps, cand_steps)
    assert is_consistent is True, "ne doit jamais etre traite comme un conflit"
    assert conflicts == []
    assert verified_count == 0, "aucune comparaison directe n'a eu lieu"
    assert len(ambiguous) == 1
    pair = ambiguous[0]
    assert "sigma" in pair.shared_symbol.lower()  # exact rendu ("sigma_max" vs "sigma_{max}") depend de latex2sympy2
    assert pair.reference_exclusive_symbols == ["N"]
    assert pair.candidate_exclusive_symbols == ["N_5"]


def test_candidate_only_quantity_is_never_a_rejection_reason():
    """Grandeur introduite uniquement par le candidat (chemin de derivation different) -> jamais comparee, jamais un rejet, jamais ambigue."""
    ref_steps = [ReferenceStepContext(formula="N_5 = 3*P*sqrt(5)", description="d")]
    cand_steps = [
        CandidateStepSummarySchema(order=1, step_type="computation", description="d", formula="W_ext = P*delta"),
    ]
    is_consistent, conflicts, verified_count, ambiguous = agent._verify_intermediate_consistency(ref_steps, cand_steps)
    assert is_consistent is True
    assert conflicts == []
    assert verified_count == 0
    assert ambiguous == []


# ---------------------------------------------------------------------------
# _resolve_symbol_correspondences (async, LLM mocké) — 3 issues explicites
# ---------------------------------------------------------------------------

def _make_ambiguous_pair():
    import sympy as sp
    N, N_5, A, omega = sp.symbols("N N_5 A omega")
    return svga_module._AmbiguousSymbolPair(
        shared_symbol="sigma_max",
        reference_expr=N / A * omega,
        candidate_expr=N_5 / A * omega,
        reference_exclusive_symbols=["N"],
        candidate_exclusive_symbols=["N_5"],
    )


def _reference_steps_ctx():
    return [
        ReferenceStepContext(formula=r"\sigma_{max} = N/A \cdot \omega", description="N = effort barre consideree."),
    ]


def _candidate_steps_ctx():
    return [
        CandidateStepSummarySchema(
            order=1, step_type="computation", description="N_5 = effort barre 5.",
            formula=r"\sigma_{max} = N_5/A \cdot \omega",
        ),
    ]


@pytest.mark.anyio
async def test_correspondence_found_and_consistent_increments_verified_no_conflict(monkeypatch):
    """Issue 1/3 : correspondance confirmée + cohérente -> verified_count += 1, aucun conflit."""
    pair = _make_ambiguous_pair()

    async def fake_invoke(task_type, messages, response_schema, context):
        return (
            _SymbolCorrespondenceSchema(correspondences=[
                _SymbolCorrespondenceEntrySchema(
                    reference_symbol="N", candidate_symbol="N_5", corresponds=True,
                    justification="Meme grandeur : N designe l'effort de la barre consideree, ici la barre 5.",
                ),
            ]),
            None, False, {},
        )

    monkeypatch.setattr(svga_module, "invoke_llm_with_fallback", fake_invoke)

    conflicts, resolved_count, note = await agent._resolve_symbol_correspondences(
        ambiguous_pairs=[pair],
        reference_steps=_reference_steps_ctx(),
        candidate_steps=_candidate_steps_ctx(),
        context=None,
    )
    assert conflicts == []
    assert resolved_count == 1
    assert "correspondance sémantique" in note


@pytest.mark.anyio
async def test_correspondence_found_but_real_disagreement_is_a_conflict(monkeypatch):
    """Issue 2/3 : correspondance confirmée mais désaccord réel après substitution -> conflit, jamais silencieux."""
    import sympy as sp
    N, N_5, A, omega = sp.symbols("N N_5 A omega")
    pair = svga_module._AmbiguousSymbolPair(
        shared_symbol="sigma_max",
        reference_expr=N / A * omega,
        candidate_expr=2 * N_5 / A * omega,  # candidat introduit un facteur 2 -- vrai desaccord
        reference_exclusive_symbols=["N"],
        candidate_exclusive_symbols=["N_5"],
    )

    async def fake_invoke(task_type, messages, response_schema, context):
        return (
            _SymbolCorrespondenceSchema(correspondences=[
                _SymbolCorrespondenceEntrySchema(
                    reference_symbol="N", candidate_symbol="N_5", corresponds=True, justification="Meme grandeur.",
                ),
            ]),
            None, False, {},
        )

    monkeypatch.setattr(svga_module, "invoke_llm_with_fallback", fake_invoke)

    conflicts, resolved_count, note = await agent._resolve_symbol_correspondences(
        ambiguous_pairs=[pair],
        reference_steps=_reference_steps_ctx(),
        candidate_steps=_candidate_steps_ctx(),
        context=None,
    )
    assert resolved_count == 1, "la comparaison a bien eu lieu (verifie), meme si le resultat est un conflit"
    assert len(conflicts) == 1
    assert "désaccord réel" in conflicts[0]


@pytest.mark.anyio
async def test_correspondence_not_found_stays_unverified_never_confused_with_the_other_two(monkeypatch):
    """Issue 3/3 : LLM ne confirme pas -> ni verified_count ni conflit, reste NON VÉRIFIÉ."""
    pair = _make_ambiguous_pair()

    async def fake_invoke(task_type, messages, response_schema, context):
        return (
            _SymbolCorrespondenceSchema(correspondences=[
                _SymbolCorrespondenceEntrySchema(
                    reference_symbol="N", candidate_symbol="N_5", corresponds=False,
                    justification="Rien dans le contexte ne confirme que N designe la barre 5 ici.",
                ),
            ]),
            None, False, {},
        )

    monkeypatch.setattr(svga_module, "invoke_llm_with_fallback", fake_invoke)

    conflicts, resolved_count, note = await agent._resolve_symbol_correspondences(
        ambiguous_pairs=[pair],
        reference_steps=_reference_steps_ctx(),
        candidate_steps=_candidate_steps_ctx(),
        context=None,
    )
    assert conflicts == [], "jamais un rejet invente faute de correspondance"
    assert resolved_count == 0, "jamais compte comme verifie non plus -- distinct des 2 autres issues"
    assert "NON VÉRIFIÉES" in note


@pytest.mark.anyio
async def test_llm_failure_treats_all_pairs_as_unresolved_never_blocking(monkeypatch):
    """Panne technique -> toutes les paires traitées comme non résolues, jamais un blocage ni une invention."""
    pair = _make_ambiguous_pair()

    async def fake_invoke_raising(task_type, messages, response_schema, context):
        raise RuntimeError("boom")

    monkeypatch.setattr(svga_module, "invoke_llm_with_fallback", fake_invoke_raising)

    conflicts, resolved_count, note = await agent._resolve_symbol_correspondences(
        ambiguous_pairs=[pair],
        reference_steps=_reference_steps_ctx(),
        candidate_steps=_candidate_steps_ctx(),
        context=None,
    )
    assert conflicts == []
    assert resolved_count == 0
    assert "échec technique" in note


@pytest.mark.anyio
async def test_llm_inventing_out_of_scope_correspondence_is_ignored(monkeypatch):
    """Une correspondance hors périmètre (symboles non proposés) ne doit jamais être appliquée."""
    pair = _make_ambiguous_pair()

    async def fake_invoke(task_type, messages, response_schema, context):
        return (
            _SymbolCorrespondenceSchema(correspondences=[
                _SymbolCorrespondenceEntrySchema(
                    reference_symbol="omega", candidate_symbol="P", corresponds=True,
                    justification="invente, hors perimetre",
                ),
            ]),
            None, False, {},
        )

    monkeypatch.setattr(svga_module, "invoke_llm_with_fallback", fake_invoke)

    conflicts, resolved_count, note = await agent._resolve_symbol_correspondences(
        ambiguous_pairs=[pair],
        reference_steps=_reference_steps_ctx(),
        candidate_steps=_candidate_steps_ctx(),
        context=None,
    )
    assert conflicts == []
    assert resolved_count == 0, "correspondance hors perimetre jamais appliquee -- reste non verifie"
