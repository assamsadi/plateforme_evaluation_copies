import type { StatusTone } from "@/components/ui/status-badge";
import type { ExerciseDifficulty, ExerciseStatus } from "@/lib/professor-api";

export const statusTone: Record<ExerciseStatus, StatusTone> = {
  draft: "neutral",
  published_as_exam: "danger",
  published_as_homework: "info",
  archived_in_library: "success",
};

export const difficultyValues: ExerciseDifficulty[] = ["facile", "intermediaire", "avance"];
