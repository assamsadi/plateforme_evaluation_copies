"""
Données de démonstration réalistes (captures d'écran / soutenance).

Ne consomme AUCUN appel LLM : tout est inséré directement en base, et les
notes/profils sont calculés avec les vrais agents déterministes du projet
(Pedagogical_Evaluation_Agent, Competency_Assessment_Agent) pour rester
cohérents avec ce que produirait le pipeline.

Usage (depuis la racine du projet, Postgres démarré) :
    PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_demo_data.py

Idempotence : abandonne si le premier exercice de démo existe déjà.
"""
import asyncio
import hashlib
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.agents.Comparative_Evaluation_Agent import DecisionEntry, SubquestionJudgment
from app.agents.Competency_Assessment_Agent import (
    CompetencyAssessmentAgent,
    CompetencyObservationRecord,
    QuestionCompetencyContribution,
)
from app.agents.Pedagogical_Evaluation_Agent import PedagogicalEvaluationAgent, QuestionEvaluationInput
from app.core.config import settings
from app.core.database import async_session_maker
from app.core.security import hash_password
from app.domain.models.academic.course import Course
from app.domain.models.academic.enrollment import Enrollment
from app.domain.models.assessment.evaluation import Evaluation
from app.domain.models.assessment.evaluation_criteria import EvaluationCriteria
from app.domain.models.assessment.exercise import Exercise, ExerciseDifficulty, ExerciseStatus
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.recommended_exercise import (
    RecommendationCategory,
    RecommendationStatus,
    RecommendedExercise,
)
from app.domain.models.assessment.student_feedback_report import StudentFeedbackReport
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.models.competency.c2pct_scaffold import find_subquestion_by_id, get_all_subquestions
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.competency.student_competency_observation import StudentCompetencyObservation
from app.domain.models.competency.student_competency_profile import CompetencyTrend, StudentCompetencyProfile
from app.domain.models.identity.user import Student, User
from app.domain.models.system_infrastructure.job import Job, JobFlowType, JobPriority, JobStatus
from app.domain.models.system_infrastructure.notification import (
    Notification,
    NotificationChannel,
    NotificationDeliveryStatus,
    NotificationPriority,
)

PASSWORD = os.environ.get("DEMO_PASSWORD", "ChangeMe-Demo-1!")
SEMESTER = "S1-2025-2026"
UTC = timezone.utc
RNG = random.Random(2026)

ALL_IDS = [sq.id for sq in get_all_subquestions()]
POINTS = {  # somme = 10 points par question
    "1.1": "0.8", "1.2": "0.6", "1.3": "0.6", "1.4": "0.6", "1.5": "0.6",
    "2.1": "0.6", "2.2": "0.8", "3.1": "1.0", "3.2": "0.8", "4": "0.6",
    "5": "1.4", "6.1": "0.5", "6.2": "0.5", "7.1": "0.3", "7.2": "0.3",
}
assert sum(Decimal(v) for v in POINTS.values()) == Decimal("10")

COMP_FR = {
    "data_and_planning": "Données et planification",
    "decomposition_and_organization": "Décomposition et organisation",
    "algorithmic_structuring": "Structuration algorithmique",
    "generalization_and_transfer": "Généralisation et transfert",
    "solution_communication": "Communication de la solution",
    "self_evaluation_and_creativity": "Auto-évaluation et créativité",
    "reflection_and_metacognition": "Réflexion et métacognition",
}
COMP_QUESTION = {
    "data_and_planning": "Avant de calculer, as-tu listé précisément les données du problème et celles qui manquaient ? Comment pourrais-tu les organiser autrement ?",
    "decomposition_and_organization": "Ton problème pourrait-il se découper en mini-problèmes indépendants ? Lesquels résoudrais-tu en premier, et pourquoi ?",
    "algorithmic_structuring": "Si tu devais expliquer tes étapes à un camarade, dans quel ordre les décrirais-tu ? Peux-tu les représenter par un schéma ?",
    "generalization_and_transfer": "Ta solution s'applique-t-elle à un autre contexte ? Qu'est-ce qui changerait, et qu'est-ce qui resterait identique ?",
    "solution_communication": "Ta réponse finale répond-elle explicitement à la question posée ? Comment la reformulerais-tu pour un lecteur qui n'a pas vu ta démarche ?",
    "self_evaluation_and_creativity": "Ton résultat est-il vraisemblable ? Comment pourrais-tu le vérifier, et existe-t-il une autre méthode plus efficace ?",
    "reflection_and_metacognition": "Quelle difficulté as-tu rencontrée, et en quoi la structure suivie t'a-t-elle aidé ou gêné ?",
}

# module_id, group_id, niveau
MODULES = [
    ("b816d86a-ee23-414d-aceb-bdf967dd17fe", "b5bbcdcb-5ff7-49ea-9943-3d101a438fc2", "L3"),
    ("ef830ec0-eb08-43e9-b555-8e445425c29f", "cdefeac9-51c9-49dc-98b3-5f36bcd4d0af", "M1"),
    ("73203191-e01a-4f36-8d77-afd861fdec78", "cc83a8ef-bf5e-40f0-92e3-6b7fd7a71b9d", "L2"),
]

# (titre, statut, difficulté, [énoncé Q1, énoncé Q2])
EXERCISES = {
    0: [
        ("Complexité des algorithmes de tri", "PUBLISHED_AS_EXAM", "INTERMEDIAIRE", [
            "Analysez la complexité temporelle du tri par insertion et du tri fusion dans le pire cas. Justifiez vos résultats.",
            "Proposez un algorithme de tri adapté à un tableau presque trié de 10^6 éléments et comparez-le au tri rapide."]),
        ("Arbres binaires de recherche", "PUBLISHED_AS_HOMEWORK", "FACILE", [
            "Insérez les valeurs 50, 30, 70, 20, 40, 60, 80 dans un arbre binaire de recherche vide, puis dessinez l'arbre obtenu.",
            "Écrivez l'algorithme de suppression d'un nœud ayant deux fils et donnez sa complexité."]),
        ("Listes chaînées, piles et files", "PUBLISHED_AS_EXAM", "INTERMEDIAIRE", [
            "Implémentez une pile à l'aide d'une liste simplement chaînée et donnez la complexité de chaque opération.",
            "Utilisez deux piles pour simuler une file. Analysez le coût amorti de l'opération de défilement."]),
    ],
    1: [
        ("Architecture en couches d'une application web", "PUBLISHED_AS_EXAM", "INTERMEDIAIRE", [
            "Proposez une architecture en couches pour une plateforme de réservation en ligne et justifiez le rôle de chaque couche.",
            "Identifiez les risques de couplage entre la couche métier et la couche d'accès aux données, puis proposez une solution."]),
        ("Patrons de conception : Factory et Observer", "PUBLISHED_AS_HOMEWORK", "INTERMEDIAIRE", [
            "Appliquez le patron Factory pour créer différents types de notifications (email, SMS, push) et schématisez la solution.",
            "Utilisez le patron Observer pour mettre à jour plusieurs vues lorsqu'un modèle change. Décrivez les échanges."]),
        ("Diagrammes UML de composants et de déploiement", "PUBLISHED_AS_EXAM", "AVANCE", [
            "Modélisez par un diagramme de composants un système de paiement en ligne composé d'une API, d'un service de facturation et d'une base de données.",
            "Représentez le déploiement de ce système sur trois serveurs et justifiez votre choix de répartition."]),
    ],
    2: [
        ("Résolution d'équations non linéaires par la méthode de Newton", "PUBLISHED_AS_EXAM", "INTERMEDIAIRE", [
            "Calculez deux itérations de la méthode de Newton pour f(x) = x² − 2 en partant de x0 = 1 et estimez l'erreur commise.",
            "Comparez la vitesse de convergence de Newton et de la dichotomie sur f(x) = cos(x) − x."]),
        ("Interpolation polynomiale de Lagrange", "PUBLISHED_AS_HOMEWORK", "FACILE", [
            "Déterminez le polynôme de Lagrange passant par les points (0,1), (1,3) et (2,2).",
            "Estimez l'erreur d'interpolation de f(x) = sin(x) sur [0, π] avec trois points équidistants."]),
        ("Intégration numérique : trapèzes et Simpson", "PUBLISHED_AS_EXAM", "INTERMEDIAIRE", [
            "Calculez ∫₀¹ e^(−x²) dx par la méthode des trapèzes avec n = 4 sous-intervalles.",
            "Refaites le calcul par la méthode de Simpson et comparez la précision obtenue."]),
    ],
}
LIBRARY = {
    0: [("Tables de hachage et gestion des collisions", "AVANCE"), ("Parcours de graphes : BFS et DFS", "INTERMEDIAIRE")],
    1: [("Microservices et communication asynchrone", "AVANCE"), ("Principes SOLID appliqués à un cas réel", "INTERMEDIAIRE")],
    2: [("Systèmes linéaires : élimination de Gauss et pivot partiel", "INTERMEDIAIRE"),
        ("Résolution numérique d'équations différentielles (Euler, Runge-Kutta)", "AVANCE")],
}

# Étudiants existants (déjà créés) + nouveaux. (prénom, nom, email, module_idx, niveau_de_base, pente, faiblesses)
STUDENTS = [
    ("Imane", "Tazi", "imane.tazi", 0, 0.82, 0.03, {}),
    ("Omar", "Fassi", "omar.fassi", 0, 0.62, -0.03, {"algorithmic_structuring": 0.28, "reflection_and_metacognition": 0.30}),
    ("Yasmine", "Ouazzani", "yasmine.ouazzani", 0, 0.78, 0.04, {}),
    ("Anas", "Kettani", "anas.kettani", 0, 0.52, -0.05, {"generalization_and_transfer": 0.30}),
    ("Nour", "Bennani", "nour.bennani", 1, 0.74, 0.0, {}),
    ("Hamza", "Chraibi", "hamza.chraibi", 1, 0.42, 0.07, {}),
    ("Sofia", "Benkirane", "sofia.benkirane", 1, 0.70, 0.01, {"self_evaluation_and_creativity": 0.35}),
    ("Mehdi", "Sqalli", "mehdi.sqalli", 1, 0.38, 0.10, {}),
    ("Meryem", "Lahlou", "meryem.lahlou", 2, 0.90, 0.0, {}),
    ("Adam", "Berrada", "adam.berrada", 2, 0.56, 0.0, {"generalization_and_transfer": 0.24}),
    ("Khadija", "Zniber", "khadija.zniber", 2, 0.86, 0.02, {}),
    ("Ilyass", "Bouazza", "ilyass.bouazza", 2, 0.60, -0.02, {"self_evaluation_and_creativity": 0.30, "solution_communication": 0.40}),
]
SUBMISSION_DATES = [datetime(2026, 9, 2, tzinfo=UTC), datetime(2026, 9, 9, tzinfo=UTC), datetime(2026, 9, 16, tzinfo=UTC)]
EXERCISE_CREATED = [datetime(2026, 8, 25, 9, tzinfo=UTC), datetime(2026, 9, 1, 9, tzinfo=UTC), datetime(2026, 9, 8, 9, tzinfo=UTC)]


def clip(x, lo=0.04, hi=1.0):
    return max(lo, min(hi, x))


def gen_judgments(perf_by_comp):
    """Un SubquestionJudgment par sous-question, cohérent avec le niveau cible de la compétence."""
    out = []
    for sq_id in ALL_IDS:
        comp = None
        for sk in C2PCTSkillCode:
            from app.domain.models.competency.c2pct_scaffold import get_competency_for_subquestion
            if get_competency_for_subquestion(sq_id) == sk:
                comp = sk
                break
        r = clip(perf_by_comp[comp.value] + RNG.gauss(0, 0.13))
        if r < 0.10:
            out.append(SubquestionJudgment(
                subquestion_id=sq_id, addressed=False, is_correct=None, evidence_reference=None,
                source="new_llm_judgment", completion_ratio=None))
            continue
        n = RNG.choice([3, 4, 5])
        present = max(1, round(r * n))
        ratio = (Decimal(present) / Decimal(n)).quantize(Decimal("0.001"))
        out.append(SubquestionJudgment(
            subquestion_id=sq_id, addressed=True, is_correct=(ratio == Decimal("1.000")),
            evidence_reference=None, source="new_llm_judgment", completion_ratio=ratio))
    return out


def decision_entries(judgments):
    from app.domain.models.competency.c2pct_scaffold import get_competency_for_subquestion
    entries = []
    for j in judgments:
        sq = find_subquestion_by_id(j.subquestion_id)
        comp = get_competency_for_subquestion(j.subquestion_id)
        if not j.addressed:
            entries.append(DecisionEntry(j.subquestion_id, comp, "NOT_ADDRESSED",
                f"La sous-question {j.subquestion_id} ({sq.label}) n'a pas été traitée dans la copie.", None))
        elif j.completion_ratio is not None and j.completion_ratio < Decimal("0.5"):
            entries.append(DecisionEntry(j.subquestion_id, comp, "INCORRECT",
                f"La sous-question {j.subquestion_id} ({sq.label}) est traitée de façon incomplète "
                f"({int(j.completion_ratio * 100)} % des éléments attendus).", None))
    return entries


async def main():
    async with async_session_maker() as s:
        first_title = EXERCISES[0][0][0]
        if (await s.execute(select(Exercise.id).where(Exercise.title == first_title))).first():
            print("ABANDON : les données de démo existent déjà.")
            return

        # --- Compte admin au nom réaliste ---
        admin = (await s.execute(select(User).where(User.email == "admin@uca.com"))).scalar_one_or_none()
        if admin is not None:
            admin.email, admin.first_name, admin.last_name = "houda.alami@uca.com", "Houda", "Alami"

        karim = (await s.execute(select(User).where(User.email == "karim.benali@uca.com"))).scalar_one()
        courses = {}
        for idx, (mod, grp, _) in enumerate(MODULES):
            courses[idx] = (await s.execute(select(Course).where(
                Course.professor_user_id == karim.id, Course.module_id == uuid.UUID(mod)))).scalar_one()

        # --- Étudiants (existants ou créés) + inscriptions ---
        h = hash_password(PASSWORD)
        students = {}
        next_num = 107
        for fn, ln, em, midx, base, slope, weak in STUDENTS:
            email = f"{em}@uca.com"
            st = (await s.execute(select(Student).where(Student.email == email))).scalar_one_or_none()
            if st is None:
                st = Student(first_name=fn, last_name=ln, email=email, hashed_password=h,
                             student_number=f"ETU-2026-{next_num}", group_id=uuid.UUID(MODULES[midx][1]),
                             enrollment_year=2025, level=MODULES[midx][2])
                next_num += 1
                s.add(st)
                await s.flush()
                s.add(Enrollment(student_id=st.id, module_id=uuid.UUID(MODULES[midx][0])))
            students[em] = st
        await s.flush()

        # --- Exercices publiés + bibliothèque ---
        exercises = {}  # (midx, i) -> (Exercise, [Question])
        library = {}
        for midx, (mod, grp, _) in enumerate(MODULES):
            for i, (title, status, diff, stmts) in enumerate(EXERCISES[midx]):
                created = EXERCISE_CREATED[i]
                ex = Exercise(
                    id=uuid.uuid4(), module_id=uuid.UUID(mod), course_id=courses[midx].id,
                    created_by_professor_id=karim.id, title=title,
                    description=f"{title} — exercice noté selon la méthodologie C2PCT (2 questions, 20 points).",
                    status=ExerciseStatus[status], difficulty_level=ExerciseDifficulty[diff],
                    deadline=SUBMISSION_DATES[i] + timedelta(days=2),
                    publication_confirmed_at=created + timedelta(hours=1),
                    publication_confirmed_hash=hashlib.sha256(title.encode()).hexdigest(),
                    created_at=created, updated_at=created)
                s.add(ex)
                await s.flush()
                qs = []
                for order, stmt in enumerate(stmts, start=1):
                    q = Question(id=uuid.uuid4(), exercise_id=ex.id, order=order, statement=stmt,
                                 covered_subquestions=list(ALL_IDS), subquestion_points=dict(POINTS),
                                 general_rules=[], created_at=created, updated_at=created)
                    s.add(q)
                    qs.append(q)
                await s.flush()
                exercises[(midx, i)] = (ex, qs)
                s.add(Job(id=uuid.uuid4(), exercise_id=ex.id, flow_type=JobFlowType.EXERCISE_SETUP,
                          status=JobStatus.COMPLETED, priority=JobPriority.NORMAL, retry_count=0,
                          started_at=created, completed_at=created + timedelta(minutes=RNG.randint(9, 16)),
                          execution_duration_ms=RNG.randint(540, 960) * 1000, worker_id="celery@worker-1",
                          progress_percentage=100, llm_call_count=RNG.randint(180, 250),
                          created_at=created, updated_at=created))
            library[midx] = []
            for title, diff in LIBRARY[midx]:
                ex = Exercise(
                    id=uuid.uuid4(), module_id=uuid.UUID(mod), course_id=None, created_by_professor_id=karim.id,
                    title=title, description=f"{title} — exercice de la bibliothèque, noté selon la méthodologie C2PCT.",
                    status=ExerciseStatus["ARCHIVED_IN_LIBRARY"], difficulty_level=ExerciseDifficulty[diff],
                    publication_confirmed_at=datetime(2026, 8, 20, 10, tzinfo=UTC),
                    publication_confirmed_hash=hashlib.sha256(title.encode()).hexdigest(),
                    created_at=datetime(2026, 8, 20, 9, tzinfo=UTC), updated_at=datetime(2026, 8, 20, 9, tzinfo=UTC))
                s.add(ex)
                await s.flush()
                s.add(Question(id=uuid.uuid4(), exercise_id=ex.id, order=1,
                               statement=f"Traitez le sujet « {title} » en suivant la démarche en 7 phases C2PCT.",
                               covered_subquestions=list(ALL_IDS), subquestion_points=dict(POINTS),
                               general_rules=[], created_at=ex.created_at, updated_at=ex.created_at))
                library[midx].append(ex)
        await s.flush()

        agent = PedagogicalEvaluationAgent()
        n_sub = 0
        # --- Copies, notes, observations, profils, feedback, recommandations ---
        for fn, ln, em, midx, base, slope, weak in STUDENTS:
            st = students[em]
            mod = uuid.UUID(MODULES[midx][0])
            obs_by_comp = {c: [] for c in C2PCTSkillCode}
            last_submission = None
            last_perf = {}
            for i in range(3):
                ex, qs = exercises[(midx, i)]
                when = SUBMISSION_DATES[i] + timedelta(hours=RNG.randint(9, 17), minutes=RNG.randint(0, 59))
                sub = Submission(id=uuid.uuid4(), exercise_id=ex.id, student_id=st.id, attempt_number=1,
                                 status=SubmissionStatus.EVALUATED, created_at=when, updated_at=when + timedelta(minutes=6))
                s.add(sub)
                await s.flush()
                perf_target = {c.value: clip(weak.get(c.value, base) + slope * i + RNG.gauss(0, 0.04)) for c in C2PCTSkillCode}
                contributions = []
                total = Decimal("0")
                for q in qs:
                    judgments = gen_judgments(perf_target)
                    result = agent.evaluate_question(QuestionEvaluationInput(
                        question_id=q.id, bareme_points=Decimal("10"), covered_subquestions=list(ALL_IDS),
                        subquestion_judgments=judgments, subquestion_points={k: Decimal(v) for k, v in POINTS.items()}))
                    entries = decision_entries(judgments)
                    report = agent.build_question_report(q.id, Decimal("10"), result, entries)
                    ev = Evaluation(id=uuid.uuid4(), submission_id=sub.id, question_id=q.id, score=result.total_score,
                                    classic_criteria_observed=[], copy_report_detail=report.to_dict(),
                                    created_at=when + timedelta(minutes=5), updated_at=when + timedelta(minutes=5))
                    s.add(ev)
                    await s.flush()
                    total += result.total_score
                    reasons_by_comp = {}
                    for e in entries:
                        reasons_by_comp.setdefault(e.competency, []).append(
                            {"subquestion_id": e.subquestion_id, "decision": e.decision, "reason": e.reason})
                    for c in result.competency_scores:
                        outcomes = [{"subquestion_id": d.subquestion_id, "addressed": d.addressed, "is_correct": d.is_correct,
                                     "completion_ratio": float(d.completion_ratio) if d.completion_ratio is not None else None}
                                    for d in c.subquestion_detail]
                        s.add(EvaluationCriteria(
                            id=uuid.uuid4(), evaluation_id=ev.id, bareme_id=None, criterion_id=None,
                            points_awarded=c.points_awarded, competency_code=c.competency_code,
                            subquestion_detail={
                                "subquestions": [{"subquestion_id": d.subquestion_id, "addressed": d.addressed,
                                                  "is_correct": d.is_correct, "source": d.source,
                                                  "completion_ratio": float(d.completion_ratio) if d.completion_ratio is not None else None}
                                                 for d in c.subquestion_detail],
                                "covered_count": c.covered_count, "successful_count": c.successful_count,
                                "success_rate": float(c.success_rate)},
                            created_at=when + timedelta(minutes=5), updated_at=when + timedelta(minutes=5)))
                        contributions.append(QuestionCompetencyContribution(
                            question_id=q.id, competency=c.competency_code, covered_count=c.covered_count,
                            successful_count=c.successful_count, subquestion_outcomes=outcomes,
                            decision_reasons=reasons_by_comp.get(c.competency_code, [])))
                # Niveau 2 — une observation par compétence pour cette copie
                perf_now = {}
                for ob in CompetencyAssessmentAgent.compute_submission_observations(contributions):
                    s.add(StudentCompetencyObservation(
                        id=uuid.uuid4(), student_id=st.id, module_id=mod, competency_code=ob.competency,
                        submission_id=sub.id, performance_copie=ob.performance_copie,
                        subquestions_covered_count=ob.subquestions_covered_count,
                        subquestions_succeeded_count=ob.subquestions_succeeded_count,
                        question_ids=[str(x) for x in ob.question_ids], subquestion_outcomes=ob.subquestion_outcomes,
                        decision_reasons=ob.decision_reasons, created_at=when + timedelta(minutes=6)))
                    obs_by_comp[ob.competency].append(CompetencyObservationRecord(
                        performance_copie=ob.performance_copie, subquestions_covered_count=ob.subquestions_covered_count,
                        subquestions_succeeded_count=ob.subquestions_succeeded_count, question_ids=ob.question_ids,
                        subquestion_outcomes=ob.subquestion_outcomes, decision_reasons=ob.decision_reasons,
                        created_at=when + timedelta(minutes=6)))
                    perf_now[ob.competency.value] = float(ob.performance_copie)
                last_submission, last_perf = sub, perf_now
                n_sub += 1
                weakest = min(perf_now, key=perf_now.get)
                strongest = max(perf_now, key=perf_now.get)
                s.add(StudentFeedbackReport(
                    id=uuid.uuid4(), student_id=st.id, module_id=mod, submission_id=sub.id,
                    feedback_text=(
                        f"Voici un retour sur ta copie « {ex.title} ».\n\n"
                        f"Tu maîtrises bien la compétence « {COMP_FR[strongest]} » ({round(perf_now[strongest] * 100)} %). "
                        f"En revanche, « {COMP_FR[weakest]} » reste fragile ({round(perf_now[weakest] * 100)} %).\n\n"
                        f"{COMP_QUESTION[weakest]}\n\n"
                        "Essaie de reprendre ce point sur un exercice de la bibliothèque, puis compare ta nouvelle démarche à celle-ci."),
                    competencies_addressed=[weakest, strongest], created_at=when + timedelta(minutes=7),
                    updated_at=when + timedelta(minutes=7)))
                s.add(Job(id=uuid.uuid4(), submission_id=sub.id, flow_type=JobFlowType.STUDENT_EVALUATION,
                          status=JobStatus.COMPLETED, priority=JobPriority.NORMAL, retry_count=0, started_at=when,
                          completed_at=when + timedelta(minutes=5), execution_duration_ms=RNG.randint(70, 240) * 1000,
                          worker_id="celery@worker-1", progress_percentage=100, llm_call_count=RNG.randint(14, 32),
                          created_at=when, updated_at=when + timedelta(minutes=5)))
                s.add(Notification(
                    id=uuid.uuid4(), user_id=st.id, type="evaluation_completed", channel=NotificationChannel.IN_APP,
                    priority=NotificationPriority.NORMAL, delivery_status=NotificationDeliveryStatus.DELIVERED,
                    delivery_attempts=1, content=f"Votre copie « {ex.title} » a été corrigée : {total} / 20.",
                    related_entity_type="Submission", related_entity_id=sub.id, action_url="/dashboard/my-exams",
                    read_at=(when + timedelta(days=1)) if i < 2 else None, created_at=when + timedelta(minutes=6),
                    updated_at=when + timedelta(minutes=6)))
                await s.flush()

            # Niveau 3 — profil de compétences (mêmes formules que le pipeline)
            lines = []
            for comp, records in obs_by_comp.items():
                if not records:
                    continue
                line = CompetencyAssessmentAgent.build_competency_line(
                    comp, records, settings.COMPETENCY_DECAY_FACTOR, settings.COMPETENCY_TREND_THRESHOLD_PERCENT,
                    settings.COMPETENCY_PERSISTENT_WEAKNESS_THRESHOLD, settings.COMPETENCY_PERSISTENT_WEAKNESS_WINDOW,
                    settings.COMPETENCY_STRENGTH_RATIO_THRESHOLD, settings.COMPETENCY_WEAKNESS_RATIO_THRESHOLD)
                lines.append(line)
                s.add(StudentCompetencyProfile(
                    id=uuid.uuid4(), student_id=st.id, competency_code=comp, module_id=mod,
                    mastery_level=line.mastery_level, trend=CompetencyTrend[line.trend],
                    last_computed_at=datetime(2026, 9, 16, 18, tzinfo=UTC), evaluations_count=line.evaluations_count,
                    confidence_level=line.confidence_level, is_persistent_weakness=line.is_persistent_weakness))

            # Recommandations : faiblesses réelles (mastery < seuil), exercices de la bibliothèque du module
            weak_lines = sorted([l for l in lines if l.mastery_level < settings.RECOMMENDATION_WEAK_MASTERY_THRESHOLD],
                                key=lambda l: (not l.is_persistent_weakness, l.mastery_level))[:2]
            for k, l in enumerate(weak_lines):
                name = COMP_FR[l.competency.value]
                s.add(RecommendedExercise(
                    id=uuid.uuid4(), student_id=st.id, module_id=mod, submission_id=last_submission.id,
                    exercise_id=library[midx][k % len(library[midx])].id, competency_code=l.competency,
                    category=RecommendationCategory.REMEDIATION, status=RecommendationStatus.ACTIVE,
                    relevance_score=Decimal(str(round(0.95 - k * 0.12 - float(l.mastery_level) / 1000, 3))),
                    reason=(f"Faiblesse persistante en « {name} » : consolider avec un exercice ciblé."
                            if l.is_persistent_weakness else
                            f"Travailler « {name} » : maîtrise actuelle de {l.mastery_level} %, en dessous du seuil de {settings.RECOMMENDATION_WEAK_MASTERY_THRESHOLD} %."),
                    created_at=datetime(2026, 9, 16, 18, tzinfo=UTC), updated_at=datetime(2026, 9, 16, 18, tzinfo=UTC)))
        await s.commit()
        print(f"OK : {len(STUDENTS)} étudiants, {len(exercises)} exercices publiés + {sum(len(v) for v in library.values())} en bibliothèque, "
              f"{n_sub} copies corrigées, profils/recommandations/feedbacks/jobs/notifications générés.")


asyncio.run(main())
