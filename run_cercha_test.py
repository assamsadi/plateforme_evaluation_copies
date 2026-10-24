import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.core.database import get_db_context
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.graph.checkpointer import get_checkpointer, setup_checkpointer_tables
from app.graph.pipeline_graph import compile_pipeline_graph
from app.graph.state import PipelineState


async def main():
    with open("CERCHA-V5-2-25.pdf", "rb") as f:
        pdf_bytes = f.read()

    async with get_db_context() as db:
        prog = Program(name=f"Test CERCHA {uuid.uuid4().hex[:8]}", code=f"P_{uuid.uuid4().hex[:8]}")
        db.add(prog)
        await db.flush()

        module = Module(program_id=prog.id, name="Test", code=f"M_{uuid.uuid4().hex[:8]}")
        db.add(module)
        await db.flush()

        professor = await SQLAlchemyUserRepository(db).create_professor(
            email=f"prof_{uuid.uuid4().hex[:8]}@test.com",
            hashed_password="hash", first_name="Prof", last_name="Test",
            department="Maths", title="Dr", employee_number=f"EMP_{uuid.uuid4().hex[:8]}",
        )

        exercise = Exercise(
            module_id=module.id, created_by_professor_id=professor.id,
            title="CERCHA-V5-2-25", status=ExerciseStatus.DRAFT,
        )
        db.add(exercise)
        await db.commit()
        exercise_id, professor_id, module_id = exercise.id, professor.id, module.id

    await setup_checkpointer_tables()

    now = datetime.now(timezone.utc)
    initial_state = PipelineState(
        thread_id=str(exercise_id), flow_type="exercise_setup", trace_id=str(exercise_id),
        exercise_id=str(exercise_id), module_id=str(module_id), professor_id=str(professor_id),
        raw_file_path="exercises/CERCHA-V5-2-25.pdf", mime_type="application/pdf",
        created_at=now, updated_at=now,
    )
    config = {"configurable": {"thread_id": str(exercise_id)}}

    with patch(
        "app.services.exercise_ocr_pipeline_service.storage_service.download",
        new_callable=AsyncMock, return_value=pdf_bytes,
    ):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            result = await graph.ainvoke(initial_state, config=config)

    print("=== RESULT ===")
    if "__interrupt__" in result:
        print("PAUSED:", result["__interrupt__"][0].value)
    else:
        print("status:", result.get("status"))
    print("exercise_id:", exercise_id)


if __name__ == "__main__":
    asyncio.run(main())
