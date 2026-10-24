"""
Schemas Pydantic pour academic_structure (Program, Group, Module, Course,
Enrollment).

Convention actée : *Create restent plats (juste des IDs en FK). *Read
utilisent le compromis "IDs + champs aplatis" — pas d'objet imbriqué
complet, juste les IDs de navigation + quelques champs d'affichage utiles
dénormalisés (ex: program_name plutôt qu'un ProgramRead entier), pour
éviter les cascades de JOIN coûteuses tout en gardant un affichage direct
sans appel supplémentaire.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel


# --- Program ---

class ProgramCreate(BaseModel):
    name: str
    code: str


class ProgramUpdate(BaseModel):
    name: str
    code: str


class ProgramRead(BaseModel):
    id: uuid.UUID
    name: str
    code: str

    model_config = {"from_attributes": True}


# --- Group ---

class GroupCreate(BaseModel):
    program_id: uuid.UUID
    label: str
    academic_year: str


class GroupRead(BaseModel):
    id: uuid.UUID
    label: str
    academic_year: str
    program_id: uuid.UUID
    program_name: str  # aplati, évite un ProgramRead complet

    model_config = {"from_attributes": True}


# --- Module ---

class ModuleCreate(BaseModel):
    program_id: uuid.UUID
    name: str
    code: str


class ModuleUpdate(BaseModel):
    name: str
    code: str


class ModuleRead(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    program_id: uuid.UUID
    program_name: str  # aplati

    model_config = {"from_attributes": True}


# --- Course ---

class CourseCreate(BaseModel):
    module_id: uuid.UUID
    group_id: uuid.UUID
    semester: str


class CourseUpdate(BaseModel):
    """
    Seul semester est éditable après création — module_id/group_id/
    professor_user_id changeraient la nature même du cours (contrainte
    unique module+groupe+semestre) plutôt que de le "modifier".
    """
    semester: str


class CourseRead(BaseModel):
    id: uuid.UUID
    semester: str
    module_id: uuid.UUID
    module_name: str          # aplati
    professor_user_id: uuid.UUID
    professor_full_name: str  # aplati (first_name + last_name concaténés)
    group_id: uuid.UUID
    group_label: str          # aplati

    model_config = {"from_attributes": True}


# --- Enrollment ---

class EnrollmentCreate(BaseModel):
    student_id: uuid.UUID
    module_id: uuid.UUID


class EnrollmentRead(BaseModel):
    id: uuid.UUID
    is_active: bool
    enrolled_at: datetime
    student_id: uuid.UUID
    student_full_name: str  # aplati
    module_id: uuid.UUID
    module_name: str        # aplati

    model_config = {"from_attributes": True}