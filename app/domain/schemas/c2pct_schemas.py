"""
Schemas Pydantic pour le suivi de compétence C2PCT (StudentCompetencyProfile).

C2PCTCompetencyRead et WeightValidationRequest ont été RETIRÉS (décisions
actées en conversation) :
- La table C2PCTCompetency a été supprimée — le fichier .md (injecté en
  contexte complet dans les agents) est désormais l'unique source de
  vérité du contenu des 7 compétences. Plus de catalogue à exposer via
  l'API ; les 7 codes fixes sont dans l'enum C2PCTSkillCode.
- QuestionC2PCTSkill a été supprimé — plus de pondération, plus de choix
  de sous-ensemble par question : les 7 compétences s'appliquent
  systématiquement, sans configuration ni validation de poids.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.competency.student_competency_profile import CompetencyTrend


class StudentCompetencyProfileRead(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    student_full_name: str      # aplati
    competency_code: C2PCTSkillCode
    module_id: uuid.UUID
    module_name: str            # aplati
    mastery_level: Decimal
    trend: CompetencyTrend
    last_computed_at: datetime

    model_config = {"from_attributes": True}


class StudentModuleOptionRead(BaseModel):
    """
    Écran "Profil de compétence" (sélecteur de module) — volontairement
    minimal (jamais ModuleRead, qui porte aussi program_id/program_name :
    superflu ici, un simple menu déroulant). Cf. docstring
    StudentCompetencyProfileRepository.list_distinct_modules_by_student
    pour pourquoi ce n'est PAS sourcé depuis Enrollment.
    """
    module_id: uuid.UUID
    module_name: str


class CompetencyObservationRead(BaseModel):
    """
    Écran "Profil de compétence" (graphique d'évolution) — UN fait
    atomique Niveau 2 (StudentCompetencyObservation), jamais l'agrégat
    Niveau 3 (StudentCompetencyReport/CompetencyProfileLine) : c'est la
    série temporelle brute qu'un graphique de courbe consomme.
    """
    competency_code: C2PCTSkillCode
    performance_copie: Decimal  # 0.0-1.0, cette soumission uniquement
    submission_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}