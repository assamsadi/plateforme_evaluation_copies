"""
Tests unitaires pour Pedagogical_Evaluation_Agent — calcul de note classique
(ticket dédié, 2026-08-18). evaluate_question_classic() est un calcul pur
déterministe (aucun appel LLM, aucun mock nécessaire) : Σ(points_critère ×
score_ratio), sauf critère disqualifying=True non satisfait -> 0 partout.

Ce fichier de test n'existait pas avant ce ticket (vérifié via Glob) — le
mécanisme C2PCT natif (evaluate_question) a ses propres scénarios validés
ailleurs (tests d'intégration réels, cf. mémoire de session), pas dupliqués ici.
"""
import uuid
from decimal import Decimal

from app.agents.Pedagogical_Evaluation_Agent import (
    ClassicCriterionJoinedInput,
    ClassicQuestionEvaluationInput,
    PedagogicalEvaluationAgent,
    CriterionReportLine,
    QuestionReport,
)

agent = PedagogicalEvaluationAgent()


def _crit(
    criterion_id: str,
    points: str,
    score_ratio: float,
    is_satisfied: bool | None,
    disqualifying: bool = False,
    label: str = "critère",
    correction_mode: str = "criteria_based",
    justification: str = "justification",
) -> ClassicCriterionJoinedInput:
    return ClassicCriterionJoinedInput(
        criterion_id=criterion_id,
        label=label,
        correction_mode=correction_mode,
        points=Decimal(points),
        disqualifying=disqualifying,
        score_ratio=score_ratio,
        is_satisfied=is_satisfied,
        justification=justification,
    )


def test_evaluate_question_classic_computes_weighted_sum():
    """Σ(points_critère × score_ratio) — cas de base, aucun critère disqualifying."""
    request = ClassicQuestionEvaluationInput(
        question_id=uuid.uuid4(),
        criteria=[
            _crit("c1", "5", 1.0, True),
            _crit("c2", "3", 0.5, False),
        ],
    )
    result = agent.evaluate_question_classic(request)
    assert result.total_score == Decimal("6.50")
    assert result.disqualified is False
    assert result.criterion_scores[0].points_awarded == Decimal("5.00")
    assert result.criterion_scores[1].points_awarded == Decimal("1.50")


def test_evaluate_question_classic_disqualifying_criterion_forces_zero():
    """
    Un critère disqualifying=True jugé non satisfait invalide la TOTALITÉ
    des points de la question, peu importe le reste (cf. docstring
    BaremeCriterionProposal.disqualifying) — même si un autre critère a un
    score_ratio parfait.
    """
    request = ClassicQuestionEvaluationInput(
        question_id=uuid.uuid4(),
        criteria=[
            _crit("c1", "5", 1.0, True),
            _crit("c2", "10", 0.0, False, disqualifying=True),
        ],
    )
    result = agent.evaluate_question_classic(request)
    assert result.total_score == Decimal("0.00")
    assert result.disqualified is True
    assert all(c.points_awarded == Decimal("0.00") for c in result.criterion_scores)
    # score_ratio individuel reste informatif malgré la disqualification.
    assert result.criterion_scores[0].score_ratio == 1.0


def test_evaluate_question_classic_disqualifying_but_satisfied_does_not_zero_out():
    """Un critère disqualifying=True SATISFAIT ne déclenche aucune pénalité — calcul normal."""
    request = ClassicQuestionEvaluationInput(
        question_id=uuid.uuid4(),
        criteria=[
            _crit("c1", "5", 1.0, True),
            _crit("c2", "10", 1.0, True, disqualifying=True),
        ],
    )
    result = agent.evaluate_question_classic(request)
    assert result.total_score == Decimal("15.00")
    assert result.disqualified is False


def test_evaluate_question_classic_disqualifying_none_is_not_disqualified():
    """is_satisfied=None (mode sans verdict booléen, ex. RUBRIC_LEVELS) n'est jamais traité comme un échec."""
    request = ClassicQuestionEvaluationInput(
        question_id=uuid.uuid4(),
        criteria=[_crit("c1", "5", 0.5, None, disqualifying=True)],
    )
    result = agent.evaluate_question_classic(request)
    assert result.disqualified is False
    assert result.total_score == Decimal("2.50")


def test_build_question_report_classic_assembles_lines_without_recompute():
    """Assemblage PUR — aucun recalcul, criterion_lines reflète exactement score_result."""
    question_id = uuid.uuid4()
    request = ClassicQuestionEvaluationInput(
        question_id=question_id,
        criteria=[_crit("c1", "5", 0.8, True, label="exactitude", correction_mode="criteria_based")],
    )
    result = agent.evaluate_question_classic(request)
    report = agent.build_question_report_classic(
        question_id=question_id,
        bareme_points=Decimal("5"),
        score_result=result,
        consigne_respected=True,
    )
    assert report.note == result.total_score
    assert report.competency_lines == []
    assert len(report.criterion_lines) == 1
    line = report.criterion_lines[0]
    assert line.criterion_id == "c1"
    assert line.label == "exactitude"
    assert line.points_awarded == result.criterion_scores[0].points_awarded
    assert report.consigne_respected is True


def test_question_report_to_dict_from_dict_roundtrip_with_criterion_lines():
    """QuestionReport.to_dict()/from_dict() doit préserver criterion_lines (nouveau champ)."""
    line = CriterionReportLine(
        criterion_id="c1", label="exactitude", correction_mode="criteria_based",
        points_possible=Decimal("5"), score_ratio=0.8, points_awarded=Decimal("4.00"),
        is_satisfied=True, justification="ok",
    )
    report = QuestionReport(
        question_id=uuid.uuid4(), note=Decimal("4.00"), bareme_points=Decimal("5"),
        criterion_lines=[line],
    )
    roundtripped = QuestionReport.from_dict(report.to_dict())
    assert roundtripped.criterion_lines[0].criterion_id == "c1"
    assert roundtripped.criterion_lines[0].points_awarded == Decimal("4.00")
    assert roundtripped.competency_lines == []
