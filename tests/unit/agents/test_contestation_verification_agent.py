"""
Tests unitaires pour Contestation_Verification_Agent — jugement LLM ciblé
de la table de vérité §3 (2026-08-18), remplaçant fuzz.ratio/partial_ratio
(trouvés incapables de distinguer un désaccord ponctuel noyé dans un long
paragraphe par ailleurs identique, cf. mémoire de session).

Couvre : le scénario réel exact qui a révélé le bug (28 vs 29 kN, bloc 4 de
copie1.jpg), les 6 cas de la table de vérité §3, et le repli déterministe
(fuzz) en cas d'échec technique UNIQUEMENT.
"""
import uuid

import pytest

import app.agents.Contestation_Verification_Agent as cva_module
from app.agents.context import AgentExecutionContext
from app.agents.contestation_verification_exceptions import AlreadyResolvedContestationError
from app.agents.Contestation_Verification_Agent import (
    ContestationCaseInput,
    ContestationVerificationAgent,
    ExtractionCorrectionSnapshot,
    _ContentConfirmationSchema,
)
from app.domain.models.assessment.extraction_correction import (
    ContestationStatus,
    ContestationType,
    ExtractionContentType,
)
from app.domain.schemas.contestation_schemas import ContestExtractionRequest

agent = ContestationVerificationAgent()
CONTEXT = AgentExecutionContext(trace_id="test-trace", flow_type="student_evaluation")


def _mock_llm(confirms: str, justification: str = "justification de test"):
    async def fake_invoke(task_type, messages, response_schema, context):
        return (
            _ContentConfirmationSchema(confirms=confirms, justification=justification),
            None, False, {},
        )
    return fake_invoke


# ---------------------------------------------------------------------------
# Scénario de référence — exact, tiré du rapport réel (bloc 4, copie1.jpg)
# ---------------------------------------------------------------------------

REAL_OCR1 = (
    "4. Vérification. La section vaut : A = \\pi d^2 / 4 avec d = 30 mm. Pour la compression "
    "de la barre 1, il faut tenir compte du flambement. La vérification donne une valeur "
    "maximale d'environ 29 kN pour P."
)
REAL_ETU = REAL_OCR1.replace("29 kN", "28 kN")
REAL_OCR2_PADDED = (
    "= 3\\sqrt{5} P. La barre 6 reprend la charge verticale : N6 = P. Les barres 1 et 2 sont "
    "donc en compression. Les barres 5 et 7 sont en traction.\n" + REAL_OCR1
)


@pytest.mark.anyio
async def test_reference_scenario_real_28_vs_29_returns_implausible(monkeypatch):
    """
    Le scénario réel exact qui a révélé le bug : fuzz.ratio(ocr1, etu) seul
    mesure déjà 99.5% (2 caractères de différence sur 203) -- aucun seuil de
    similarité ne peut trancher. Le jugement LLM, lui, doit reconnaître que
    ocr2 (bien que plus long, contexte voisin inclus) confirme "29" (donc
    l'extraction d'origine), pas "28" (la réclamation).
    """
    monkeypatch.setattr(
        cva_module, "invoke_llm_with_fallback",
        _mock_llm("ORIGINAL", "La relecture confirme '29 kN', pas '28 kN' réclamé par l'étudiant."),
    )
    verdict, content, justification, anomaly = await agent._apply_content_truth_table(
        ocr1=REAL_OCR1, etu=REAL_ETU, ocr2=REAL_OCR2_PADDED, ocr2_confidence=0.95, context=CONTEXT,
    )
    assert verdict == "IMPLAUSIBLE"
    assert content == REAL_OCR1
    assert anomaly is False
    assert "29" in justification


# ---------------------------------------------------------------------------
# Table de vérité §3 — 6 cas
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_line5_low_confidence_returns_ambigu_never_calls_llm(monkeypatch):
    """Ligne 5 : prime sur tout le reste, vérifiée AVANT tout jugement LLM."""
    call_count = 0

    async def fake_invoke(task_type, messages, response_schema, context):
        nonlocal call_count
        call_count += 1
        return _ContentConfirmationSchema(confirms="ORIGINAL", justification="x"), None, False, {}

    monkeypatch.setattr(cva_module, "invoke_llm_with_fallback", fake_invoke)
    verdict, content, justification, anomaly = await agent._apply_content_truth_table(
        ocr1="A", etu="B", ocr2="C", ocr2_confidence=0.3, context=CONTEXT,
    )
    assert verdict == "AMBIGU"
    assert content is None
    assert call_count == 0, "le jugement LLM ne doit jamais etre appele si la confiance OCR2 est trop basse"


@pytest.mark.anyio
async def test_line1_confirms_original_returns_implausible(monkeypatch):
    monkeypatch.setattr(cva_module, "invoke_llm_with_fallback", _mock_llm("ORIGINAL"))
    verdict, content, _j, anomaly = await agent._apply_content_truth_table(
        ocr1="original", etu="reclamation", ocr2="relecture", ocr2_confidence=0.9, context=CONTEXT,
    )
    assert verdict == "IMPLAUSIBLE"
    assert content == "original"
    assert anomaly is False


@pytest.mark.anyio
async def test_line2_confirms_claimed_returns_plausible(monkeypatch):
    monkeypatch.setattr(cva_module, "invoke_llm_with_fallback", _mock_llm("CLAIMED"))
    verdict, content, _j, anomaly = await agent._apply_content_truth_table(
        ocr1="original", etu="reclamation", ocr2="relecture", ocr2_confidence=0.9, context=CONTEXT,
    )
    assert verdict == "PLAUSIBLE"
    assert content == "reclamation"
    assert anomaly is False


@pytest.mark.anyio
async def test_line3_confirms_both_returns_plausible_degenerate_with_anomaly_flag(monkeypatch):
    """Cas dégénéré : réclamation == extraction d'origine -- PLAUSIBLE mais anomaly_flag=True pour audit."""
    monkeypatch.setattr(cva_module, "invoke_llm_with_fallback", _mock_llm("BOTH"))
    verdict, content, justification, anomaly = await agent._apply_content_truth_table(
        ocr1="meme contenu", etu="meme contenu", ocr2="relecture", ocr2_confidence=0.9, context=CONTEXT,
    )
    assert verdict == "PLAUSIBLE"
    assert content == "meme contenu"
    assert anomaly is True
    assert "dégénéré" in justification.lower() or "degenere" in justification.lower()


@pytest.mark.anyio
async def test_line4_confirms_neither_third_content_returns_ambigu(monkeypatch):
    """Ligne 4 : un troisieme contenu emerge, ni l'original ni la reclamation."""
    monkeypatch.setattr(
        cva_module, "invoke_llm_with_fallback",
        _mock_llm("NEITHER", "La relecture donne une troisieme valeur, differente des deux."),
    )
    verdict, content, _j, anomaly = await agent._apply_content_truth_table(
        ocr1="valeur A", etu="valeur B", ocr2="valeur C", ocr2_confidence=0.9, context=CONTEXT,
    )
    assert verdict == "AMBIGU"
    assert content is None
    assert anomaly is False


@pytest.mark.anyio
async def test_line6_confirms_neither_genuinely_ambiguous_returns_ambigu(monkeypatch):
    """Ligne 6 : ecriture reellement ambigue, meme branche que la ligne 4 mais scenario distinct."""
    monkeypatch.setattr(
        cva_module, "invoke_llm_with_fallback",
        _mock_llm("NEITHER", "L'ecriture est trop ambigue pour trancher entre les deux hypotheses."),
    )
    verdict, content, _j, anomaly = await agent._apply_content_truth_table(
        ocr1="valeur A", etu="valeur B", ocr2="texte illisible", ocr2_confidence=0.9, context=CONTEXT,
    )
    assert verdict == "AMBIGU"
    assert content is None
    assert anomaly is False


# ---------------------------------------------------------------------------
# Repli déterministe (fuzz) -- UNIQUEMENT en cas d'échec technique du LLM
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_llm_technical_failure_falls_back_to_fuzzy_never_blocking(monkeypatch):
    async def fake_invoke_raising(task_type, messages, response_schema, context):
        raise RuntimeError("panne technique simulee")

    monkeypatch.setattr(cva_module, "invoke_llm_with_fallback", fake_invoke_raising)

    # ocr2 identique a ocr1 (texte court, fuzz.ratio fiable ici) -> repli doit
    # quand meme produire un verdict correct, jamais un blocage.
    verdict, content, justification, _anomaly = await agent._apply_content_truth_table(
        ocr1="P = 28 kN", etu="P = 29 kN", ocr2="P = 28 kN", ocr2_confidence=0.9, context=CONTEXT,
    )
    assert verdict == "IMPLAUSIBLE"
    assert content == "P = 28 kN"
    assert "repli" in justification.lower() or "échec" in justification.lower()


@pytest.mark.anyio
async def test_llm_call_is_the_primary_path_not_fuzzy_by_default(monkeypatch):
    """
    Vérification directe de l'exigence : le jugement LLM est le mécanisme
    PRINCIPAL. Avec un ocr2 qui matcherait fuzzy-wise ocr1 ET etu (long
    paragraphe, différence ponctuelle noyée -- comme le cas réel), seul un
    LLM qui répond explicitement peut distinguer -- si le mock LLM répond
    CLAIMED, le résultat doit suivre le LLM, jamais un score fuzz qui
    aurait pu dire autre chose.
    """
    monkeypatch.setattr(cva_module, "invoke_llm_with_fallback", _mock_llm("CLAIMED"))
    verdict, content, _j, _a = await agent._apply_content_truth_table(
        ocr1=REAL_OCR1, etu=REAL_ETU, ocr2=REAL_OCR2_PADDED, ocr2_confidence=0.95, context=CONTEXT,
    )
    assert verdict == "PLAUSIBLE"
    assert content == REAL_ETU


# ---------------------------------------------------------------------------
# §2 étape 8 — garde-fou anti-double-passage : un bloc déjà tranché ne doit
# JAMAIS repasser automatiquement par l'agent (escalade professeur only).
# Vérification purement déterministe (le garde est la toute première ligne
# d'execute(), avant tout appel LLM) -- aucun monkeypatch LLM nécessaire.
# ---------------------------------------------------------------------------

def _make_case(contestation_status: ContestationStatus | None) -> ContestationCaseInput:
    contested = ExtractionCorrectionSnapshot(
        id=uuid.uuid4(),
        submission_id=uuid.uuid4(),
        image_crop_path="test/block.png",
        content_type=ExtractionContentType.TEXT,
        prediction_ocr="P = 29 kN",
        bounding_box={"x": 0, "y": 0, "width": 100, "height": 100},
        evidence_level="label_explicite",
        page_number=1,
        contestation_status=contestation_status,
    )
    request = ContestExtractionRequest(
        contestation_type=ContestationType.CONTENT, claimed_content="P = 28 kN",
    )
    return ContestationCaseInput(contested=contested, request=request)


@pytest.mark.parametrize("blocked_status", [
    ContestationStatus.IMPLAUSIBLE,
    ContestationStatus.AMBIGU,
    ContestationStatus.RESOLVED,
])
@pytest.mark.anyio
async def test_second_pass_on_already_resolved_block_is_rejected(blocked_status):
    """
    §2 étape 8 : IMPLAUSIBLE (notre scénario réel 29 vs 28 kN une fois
    tranché), AMBIGU, et RESOLVED bloquent tous les trois un second passage
    automatique -- jamais une nouvelle tentative LLM, seule l'escalade
    professeur (teacher_arbitration_node) est prévue après ce point.
    """
    case = _make_case(blocked_status)
    with pytest.raises(AlreadyResolvedContestationError) as exc_info:
        await agent.execute(case, CONTEXT)
    assert exc_info.value.current_status == blocked_status.value


@pytest.mark.anyio
async def test_pending_verification_status_is_never_blocked(monkeypatch):
    """Non-régression : un bloc PAS encore tranché (statut normal avant tout verdict) ne doit jamais être bloqué à tort."""
    monkeypatch.setattr(cva_module, "invoke_llm_with_fallback", _mock_llm("ORIGINAL"))

    async def fake_reread(*args, **kwargs):
        return "P = 29 kN", 0.95, "gemini:test", "crop/path.png", False
    monkeypatch.setattr(agent, "_run_blind_ocr2_reread", fake_reread)

    case = _make_case(ContestationStatus.PENDING_VERIFICATION)
    verdict = await agent.execute(case, CONTEXT)
    assert verdict.verdict == "IMPLAUSIBLE"
