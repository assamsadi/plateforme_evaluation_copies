"""
Schémas Pydantic pour la validation déterministe (étape 5) des blocs STRUCTURE
produits par OCR_Extraction_Agent v3.
"""
from pydantic import BaseModel, Field

from app.domain.models.assessment.extraction_correction import ExtractionOrigin, StructureType


class StructureElement(BaseModel):
    content: str
    origin: ExtractionOrigin
    is_struck_through: bool = False


class TableCell(StructureElement):
    pass


class TableRow(BaseModel):
    cells: list[TableCell]


class TableStructure(BaseModel):
    rows: list[TableRow]


class FormField(BaseModel):
    label: str
    label_origin: ExtractionOrigin
    value: str | None = None
    value_origin: ExtractionOrigin | None = None
    is_checked: bool | None = None
    is_struck_through: bool = False


class FormStructure(BaseModel):
    fields: list[FormField]


class AnnotatedDiagramElement(BaseModel):
    id: str
    type: str
    content: str
    origin: ExtractionOrigin
    is_struck_through: bool = False


class AnnotatedDiagramRelation(BaseModel):
    from_id: str
    to_id: str
    type: str


class AnnotatedDiagramStructure(BaseModel):
    elements: list[AnnotatedDiagramElement]
    relations: list[AnnotatedDiagramRelation] = Field(default_factory=list)


class MultiColumnListStructure(BaseModel):
    columns: list[list[StructureElement]]


STRUCTURE_VALIDATORS: dict[StructureType, type[BaseModel]] = {
    StructureType.TABLE: TableStructure,
    StructureType.FORM: FormStructure,
    StructureType.ANNOTATED_DIAGRAM: AnnotatedDiagramStructure,
    StructureType.MULTI_COLUMN_LIST: MultiColumnListStructure,
    StructureType.OTHER: TableStructure,
}
