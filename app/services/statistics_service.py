"""
Service Statistics — calcul des statistiques académiques et moyennes.

get_student_competency_profile RETIRÉE (correctif découvertes annexes,
priorité 3) — appelait competency_profile_repo.get_by_student (méthode
jamais définie sur StudentCompetencyProfileRepositoryProtocol) et lisait
p.skill_code/p.last_evaluated_at (champs inexistants sur StudentCompetency
Profile) : plantait à coup sûr en 500 dès qu'exercée, jamais appelée
ailleurs que par GET /students/me/competency-profile (results_router.py),
qui délègue désormais directement à CompetencyAssessmentService.get_report
(même mécanisme que GET /students/{student_id}/competency-profile,
construit au chantier précédent) — competency_profile_repo retiré du
constructeur avec elle, plus aucun appelant.

Correctif "statistiques admin" — get_exercise_stats() ET get_student_stats()
étaient TOUTES LES DEUX cassées à deux niveaux (pas seulement le champ
.grade inexistant décrit dans le rapport initial) : elles appelaient
evaluation_repo.list_by_exercise()/list_by_student(), des méthodes qui
n'existaient PAS DU TOUT sur EvaluationRepositoryProtocol (seul le champ
.score existe sur Evaluation, jamais .grade). get_student_stats() est
câblée sur GET /students/me/stats (results_router.py) : plantait donc en
AttributeError dès le premier appel réel, jamais détecté faute de test.
Les deux méthodes de repository ont été ajoutées (jointure via Submission,
cf. evaluation_repository.py) et les deux services corrigés pour lire
.score.

get_platform_stats() (nouveau) — statistiques à l'échelle de toute la
plateforme pour l'admin. La moyenne globale est la moyenne des notes
TOTALES par copie (somme des Evaluation.score d'une soumission), pour
s'exprimer sur l'échelle réelle de l'examen (ex. /20) et non par question
— à la différence de get_exercise_stats/get_student_stats, qui gardent la
moyenne brute de Evaluation.score par question.
"""
import uuid
from typing import Protocol, Any

from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.models.assessment.submission import SubmissionStatus
from app.domain.models.identity.user import UserRole
from app.domain.repositories.evaluation_repository import EvaluationRepositoryProtocol
from app.domain.repositories.exercise_repository import ExerciseRepositoryProtocol
from app.domain.repositories.submission_repository import SubmissionRepositoryProtocol
from app.domain.repositories.user_repository import UserRepositoryProtocol


class StatisticsServiceProtocol(Protocol):
    async def get_exercise_stats(self, exercise_id: uuid.UUID) -> dict[str, Any]: ...
    async def get_student_stats(self, student_id: uuid.UUID) -> dict[str, Any]: ...
    async def get_platform_stats(self) -> dict[str, Any]: ...


class StatisticsService:
    def __init__(
        self,
        evaluation_repo: EvaluationRepositoryProtocol,
        exercise_repo: ExerciseRepositoryProtocol,
        submission_repo: SubmissionRepositoryProtocol,
        user_repo: UserRepositoryProtocol,
    ) -> None:
        self._evaluation_repo = evaluation_repo
        self._exercise_repo = exercise_repo
        self._submission_repo = submission_repo
        self._user_repo = user_repo

    async def get_exercise_stats(self, exercise_id: uuid.UUID) -> dict[str, Any]:
        evaluations = await self._evaluation_repo.list_by_exercise(exercise_id)
        if not evaluations:
            return {
                "exercise_id": str(exercise_id),
                "total_evaluations": 0,
                "average_score": None,
                "min_score": None,
                "max_score": None,
            }

        scores = [e.score for e in evaluations if e.score is not None]
        if not scores:
            return {
                "exercise_id": str(exercise_id),
                "total_evaluations": len(evaluations),
                "average_score": None,
                "min_score": None,
                "max_score": None,
            }

        avg = float(sum(scores) / len(scores))
        return {
            "exercise_id": str(exercise_id),
            "total_evaluations": len(evaluations),
            "average_score": round(avg, 2),
            "min_score": float(min(scores)),
            "max_score": float(max(scores)),
        }

    async def get_student_stats(self, student_id: uuid.UUID) -> dict[str, Any]:
        """
        Bug corrigé : total_submissions comptait len(list_by_student(...)
        .items), une méthode PAGINÉE (50 par défaut, jamais overridé ici)
        — silencieusement plafonné à 50 pour tout étudiant en ayant
        davantage, jamais un vrai total. count_by_student() fait un COUNT
        natif, jamais de lignes chargées juste pour être comptées.
        """
        total_submissions = await self._submission_repo.count_by_student(student_id)
        evaluations = await self._evaluation_repo.list_by_student(student_id)

        scores = [e.score for e in evaluations if e.score is not None]
        avg = float(sum(scores) / len(scores)) if scores else None

        return {
            "student_id": str(student_id),
            "total_submissions": total_submissions,
            "total_evaluations": len(evaluations),
            "average_score": round(avg, 2) if avg is not None else None,
        }

    async def get_platform_stats(self) -> dict[str, Any]:
        users_by_role = await self._user_repo.count_by_role()
        exercises_by_status = await self._exercise_repo.count_by_status()
        submissions_by_status = await self._submission_repo.count_by_status()
        average_score = await self._evaluation_repo.get_average_score_platform()

        # Les repositories ne renvoient que les valeurs réellement présentes
        # en base (GROUP BY) — le contrat de sortie API expose TOUJOURS
        # toutes les valeurs d'enum connues, à 0 si absentes (jamais une clé
        # manquante devinée côté client).
        users_by_role = {role.value: users_by_role.get(role.value, 0) for role in UserRole}
        exercises_by_status = {
            status.value: exercises_by_status.get(status.value, 0) for status in ExerciseStatus
        }
        submissions_by_status = {
            status.value: submissions_by_status.get(status.value, 0) for status in SubmissionStatus
        }

        return {
            "total_users": sum(users_by_role.values()),
            "users_by_role": users_by_role,
            "total_exercises": sum(exercises_by_status.values()),
            "exercises_by_status": exercises_by_status,
            "total_submissions": sum(submissions_by_status.values()),
            "submissions_by_status": submissions_by_status,
            "average_score": round(float(average_score), 2) if average_score is not None else None,
        }
