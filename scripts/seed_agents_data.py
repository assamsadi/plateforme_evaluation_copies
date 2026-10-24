"""
Fausses données "agents" pour le compte professeur (captures d'écran / soutenance) :
journaux de décision des agents, variantes de solution + graphes de raisonnement,
clarifications, arbitrages de contestations d'extraction, incidents, recours de notes.

Nécessite scripts/seed_demo_data.py puis scripts/seed_ocr_data.py déjà exécutés.
Aucun appel LLM. Usage : PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_agents_data.py
"""
import ast
import asyncio
import json
import pathlib
import random
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text

from app.core.database import async_session_maker

UTC = timezone.utc
RNG = random.Random(777)

# Réutilise le contenu pédagogique déjà défini dans seed_ocr_data.py (sans l'exécuter).
_src = pathlib.Path(__file__).with_name("seed_ocr_data.py").read_text(encoding="utf-8")
CONTENT = ast.literal_eval(_src.split("CONTENT = ", 1)[1].split("\n\n\ndef render", 1)[0])

ALT = {
    "Complexité des algorithmes de tri": "Théorème maître : T(n) = 2T(n/2) + n avec a = 2, b = 2 et f(n) = n, donc T(n) = O(n log n).",
    "Arbres binaires de recherche": "Insertion récursive : comparer la valeur à la racine puis descendre dans le sous-arbre concerné.",
    "Listes chaînées, piles et files": "Tableau dynamique redimensionnable : empiler en O(1) amorti.",
    "Architecture en couches d'une application web": "Architecture hexagonale : domaine au centre, adaptateurs pour l'interface et la persistance.",
    "Patrons de conception : Factory et Observer": "Factory Method : des sous-classes de créateurs redéfinissent la méthode de fabrication.",
    "Diagrammes UML de composants et de déploiement": "Diagramme de composants avec ports explicites et connecteurs d'assemblage et de délégation.",
    "Résolution d'équations non linéaires par la méthode de Newton": "Méthode de la sécante : x(n+1) = x(n) - f(x(n)) (x(n) - x(n-1)) / (f(x(n)) - f(x(n-1))), sans dérivée.",
    "Interpolation polynomiale de Lagrange": "Différences divisées de Newton : P(x) = 1 + 2x - 1,5 x (x - 1).",
    "Intégration numérique : trapèzes et Simpson": "Quadrature de Gauss-Legendre à 2 points sur [0, 1].",
}
DIFF = {"FACILE": "FACILE", "INTERMEDIAIRE": "INTERMEDIAIRE", "AVANCE": "AVANCE"}


async def q(s, sql, **p):
    return (await s.execute(text(sql), p)).all()


async def ins(s, table, row, casts=None):
    casts = casts or {}
    cols = ", ".join(f'"{c}"' for c in row)
    vals = ", ".join(f"CAST(:{c} AS {casts[c]})" if c in casts else f":{c}" for c in row)
    def val(k, v):
        if casts.get(k) == "jsonb":
            return json.dumps(v, ensure_ascii=False)
        if casts.get(k) == "timestamptz" and isinstance(v, str):
            return datetime.fromisoformat(v)
        return v

    await s.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({vals})"), {k: val(k, v) for k, v in row.items()})


def log_row(agent, etype, eid, thread, node, when, inp, outp, just, conf, llm, tools, status="NOT_REVIEWED", prof=None, corr=None):
    return dict(
        id=uuid.uuid4(), agent_name=agent, related_entity_type=etype, related_entity_id=eid, input_summary=inp, output_summary=outp,
        justification=just, confidence_score=(round(conf, 3) if conf is not None else None),
        model_version="gemini-flash-lite-latest" if llm else "deterministic", prompt_version="v3" if llm else None,
        tools_consulted=tools, execution_time_ms=RNG.randint(900, 9000) if llm else RNG.randint(4, 45),
        token_count_input=RNG.randint(900, 6000) if llm else None, token_count_output=RNG.randint(150, 900) if llm else None,
        thread_id=thread, run_id=f"run-{str(thread)[:8]}", node_name=node, professor_validation_status=status,
        professor_correction=corr, validated_by_professor_id=prof if status != "NOT_REVIEWED" else None, created_at=when)


async def main():
    async with async_session_maker() as s:
        if (await q(s, "select 1 from agent_decision_logs where agent_name='Feedback_Agent' limit 1")):
            print("ABANDON : des journaux d'agents de démo existent déjà.")
            return
        karim = (await q(s, "select id from users where email='karim.benali@uca.com'"))[0][0]
        exs = await q(s, "select id, title, difficulty_level, created_at from exercises where created_by_professor_id=:k and status in ('PUBLISHED_AS_EXAM','PUBLISHED_AS_HOMEWORK') order by created_at, exercise_number", k=karim)
        qs = {e[0]: await q(s, 'select id, "order", statement from questions where exercise_id=:e order by "order"', e=e[0]) for e in exs}
        subs = await q(s, "select s.id, s.exercise_id, s.student_id, s.created_at, u.first_name from submissions s join users u on u.id=s.student_id where s.exercise_id = any(:ids) order by s.created_at", ids=[e[0] for e in exs])

        # ---------------- Variantes de solution + graphes de raisonnement ----------------
        n_var = 0
        ai_states = ["PENDING_VALIDATION"] * 6 + ["APPROVED", "APPROVED", "REJECTED"]
        for ei, (eid, title, diff, created) in enumerate(exs):
            for qid, order, stmt in qs[eid]:
                intro, formula, concl = CONTENT[title][order - 1]
                variants = [("TEACHER_ORIGINAL", True, "APPROVED", f"{intro} {formula}. {concl}", (intro, formula, concl))]
                if order == 1:
                    alt = ALT[title]
                    variants.append(("AI_GENERATED", False, ai_states[ei], f"Méthode alternative proposée par l'IA : {alt}", ("Mêmes données que la référence.", alt, "Le résultat obtenu est identique à celui de la correction.")))
                for source, is_ref, status, content, (t1, t2, t3) in variants:
                    vid = uuid.uuid4()
                    when = created + timedelta(minutes=14 if is_ref else 22)
                    await ins(s, "solution_variants", dict(
                        id=vid, question_id=qid, content=content, is_reference=is_ref, source=source, difficulty_level=DIFF[diff],
                        status=status, version=1, created_at=when, updated_at=when,
                        validated_by_professor_id=karim if status in ("APPROVED", "REJECTED") and not is_ref else None,
                        review_comment=("Variante pertinente, méthode bien distincte de la référence." if status == "APPROVED" and not is_ref
                                        else "Rejetée : la démarche reste identique à la correction du professeur." if status == "REJECTED" else None),
                        reasoning_summary=None),
                        casts={"source": "variant_source", "difficulty_level": "variant_difficulty", "status": "variant_status"})
                    steps = [("GIVEN_DATA", t1, None, "DATA_AND_PLANNING"), ("FORMULA_APPLICATION", t2, t2, "ALGORITHMIC_STRUCTURING"),
                             ("COMPUTATION", "Application numérique de la formule aux données de l'énoncé.", None, "ALGORITHMIC_STRUCTURING"),
                             ("CONCLUSION", t3, None, "SOLUTION_COMMUNICATION")]
                    prev = None
                    for k, (stype, desc, formula_, comp) in enumerate(steps, start=1):
                        sid = uuid.uuid4()
                        await ins(s, "reasoning_steps", dict(
                            id=sid, variant_id=vid, order=k, step_type=stype, description=desc, formula=formula_,
                            concept_tags=[], tools_used=["sympy"] if stype == "FORMULA_APPLICATION" else [], related_competency_code=comp,
                            extraction_signals=None, version=1, created_at=when, updated_at=when),
                            casts={"step_type": "reasoning_step_type", "related_competency_code": "c2pct_skill_code",
                                   "concept_tags": "jsonb", "tools_used": "jsonb", "extraction_signals": "jsonb"})
                        if prev:
                            await ins(s, "reasoning_step_dependencies", dict(id=uuid.uuid4(), step_id=sid, depends_on_step_id=prev))
                        prev = sid
                    n_var += 1

        # ---------------- Journaux de décision des agents ----------------
        n_log = 0
        for eid, title, diff, created in exs:
            first_q = qs[eid][0][0]
            rows = [
                ("OCR_Extraction_Agent", "Exercise", eid, "document_structuring_node", 0, "Document de référence (2 pages) lu en vision.", "8 blocs extraits (texte, équations).", "Lecture vision Gemini, contrôle LaTeX déterministe validé.", RNG.uniform(0.86, 0.97), True, ["opencv", "pylatexenc"]),
                ("Document_Structuring_Agent", "Exercise", eid, "document_structuring_node", 2, "8 blocs classés (énoncé, correction).", "1 section, 2 questions, corrections rattachées.", "Regroupement des blocs par numéro de question, complétude COMPLETE.", RNG.uniform(0.9, 0.98), True, []),
                ("Extraction_Verification_Agent", "Question", first_q, "extraction_verification_node", 5, "Correction de la question 1.", "Décomposition en 4 étapes, barème C2PCT natif extrait (15 sous-questions).", "Sous-questions couvertes déduites du barème chiffré du professeur.", RNG.uniform(0.85, 0.96), True, ["sympy", "pint"]),
                ("Reasoning_Graph_Agent", "Question", first_q, "reasoning_graph_node", 8, "4 étapes déjà décomposées.", "Graphe acyclique valide, 3 arêtes de dépendance.", "Dépendances déduites de l'ordre logique, validation NetworkX sans cycle.", RNG.uniform(0.8, 0.95), True, ["networkx"]),
                ("Solution_Variant_Generation_Agent", "Question", first_q, "solution_variant_generation_node", 11, "Solution de référence + méthode imposée absente.", "1 variante IA proposée (méthode alternative).", "Candidate acceptée : vérifiée par SymPy et stratégiquement distincte de la référence.", RNG.uniform(0.78, 0.93), True, ["sympy"]),
            ]
            for agent, et, ent, node, dm, inp, outp, just, conf, llm, tools in rows:
                st = "VALIDATED" if agent == "Extraction_Verification_Agent" else "NOT_REVIEWED"
                await ins(s, "agent_decision_logs", log_row(agent, et, ent, eid, node, created + timedelta(minutes=dm), inp, outp, just, conf, llm, tools, st, karim),
                          casts={"tools_consulted": "jsonb", "professor_validation_status": "professor_validation_status"})
                n_log += 1
        for sid, eid, stid, when, fn in subs:
            rows = [
                ("Question_Attachment_Agent", "Submission", sid, "question_attachment_node", 1, "8 blocs OCR de la copie.", "8 blocs rattachés (label explicite ou embeddings).", "Niveaux 1 et 2 concluants, aucun arbitrage LLM nécessaire.", RNG.uniform(0.85, 0.99), True, ["rapidfuzz", "sentence-transformers/all-MiniLM-L6-v2"]),
                ("Comparative_Evaluation_Agent", "Submission", sid, "comparative_evaluation_node", 3, "Réponse de l'étudiant vs correction de référence (15 sous-questions).", "Jugement par sous-question, completion_ratio calculé en code.", "Éléments vérifiables comparés sur le fond, sans similarité textuelle.", RNG.uniform(0.78, 0.96), True, []),
                ("Pedagogical_Evaluation_Agent", "Submission", sid, "evaluation_node", 4, "Jugements par sous-question, barème C2PCT.", "Note calculée par compétence (points = part du barème x taux de réussite).", "Calcul déterministe, aucune décision LLM.", None, False, []),
                ("Competency_Assessment_Agent", "Submission", sid, "competency_assessment_node", 5, "Notes de la copie entière.", "7 observations de compétences, profil mis à jour.", "Agrégation Niveau 2 pondérée + décroissance exponentielle Niveau 3.", None, False, []),
                ("Recommendation_Agent", "Submission", sid, "recommendation_node", 6, "Profil de compétences à jour.", "Recommandations d'exercices ciblées.", "Priorisation par palier : faiblesse persistante, faible maîtrise, vérification.", None, False, []),
                ("Feedback_Agent", "Submission", sid, "feedback_node", 7, "Faiblesses et points forts réels de la copie.", "Feedback socratique généré.", "Texte ancré sur les extraits réels, au moins une question posée.", RNG.uniform(0.82, 0.95), True, []),
            ]
            for agent, et, ent, node, dm, inp, outp, just, conf, llm, tools in rows:
                r = RNG.random()
                st, corr = "NOT_REVIEWED", None
                if agent == "Comparative_Evaluation_Agent":
                    st = "VALIDATED" if r < 0.25 else "CORRECTED" if r < 0.30 else "NOT_REVIEWED"
                    corr = "Ajustement : la sous-question 3.2 était traitée par un schéma, à valoriser." if st == "CORRECTED" else None
                await ins(s, "agent_decision_logs", log_row(agent, et, ent, sid, node, when + timedelta(minutes=dm), inp, outp, just, conf, llm, tools, st, karim, corr),
                          casts={"tools_consulted": "jsonb", "professor_validation_status": "professor_validation_status"})
                n_log += 1

        # ---------------- Clarifications ----------------
        by_title = {t: (e, qs[e]) for e, t, d, c in exs}
        def qid(title, order): return by_title[title][1][order - 1][0]
        N = "Résolution d'équations non linéaires par la méthode de Newton"
        clar = [
            ("Question", qid(N, 1), "warning", "PENDING", "L'étape « x1 = 1 − (1−2)/2 » utilise f'(x) = 2x sans la poser explicitement : la correction doit-elle l'énoncer avant le calcul ?", "Oui, poser f'(x) = 2x avant l'application de la formule.", None, None, None),
            ("Question", qid("Complexité des algorithmes de tri", 2), "informational", "PENDING", "La complexité O(n + k) ne définit pas k dans la correction : faut-il préciser qu'il s'agit du nombre d'inversions ?", "k = nombre d'inversions du tableau.", None, None, None),
            ("Question", qid("Diagrammes UML de composants et de déploiement", 2), "warning", "PENDING", "Deux répartitions de déploiement sont compatibles avec la correction. Laquelle doit servir de référence pour la notation ?", None, None, None, None),
            ("Question", qid("Intégration numérique : trapèzes et Simpson", 1), "informational", "PENDING", "La valeur exacte 0,7468 est citée sans source : la correction accepte-t-elle une tolérance de ±0,0005 ?", "Oui, tolérance de ±0,0005.", None, None, None),
            ("Question", qid("Interpolation polynomiale de Lagrange", 1), "informational", "ANSWERED", "Le polynôme P(x) = 1 + 3,5x − 1,5x² est-il la seule forme acceptée ?", "Toute forme équivalente est acceptée.", "Toute forme équivalente (Lagrange, Newton) est acceptée si elle passe par les trois points.", "2026-09-05 14:20+00", None),
            ("Question", qid("Arbres binaires de recherche", 2), "warning", "ANSWERED", "La suppression par prédécesseur est-elle aussi acceptée ?", "Oui, symétrique du successeur.", "Oui : prédécesseur ou successeur sont deux réponses valides.", "2026-09-04 09:45+00", None),
        ]
        for et, eid_, sev, st, qtxt, prop, ans, ans_at, _ in clar:
            await ins(s, "reasoning_clarification_requests", dict(
                id=uuid.uuid4(), agent_question=qtxt, status=st, related_entity_type=et, related_entity_id=eid_, severity=sev,
                proposed_answer=prop, professor_answer=ans, answered_by_professor_id=karim if ans else None,
                answered_at=ans_at, created_at="2026-09-03 10:00+00", updated_at="2026-09-03 10:00+00"),
                casts={"status": "clarification_status", "severity": "clarification_severity", "answered_at": "timestamptz", "created_at": "timestamptz", "updated_at": "timestamptz"})
        # clarification bloquante d'évaluation (réponse alternative d'un étudiant)
        anas = next(x for x in subs if x[4] == "Anas" and x[1] == by_title["Complexité des algorithmes de tri"][0])
        await ins(s, "reasoning_clarification_requests", dict(
            id=uuid.uuid4(), agent_question="La réponse de l'étudiant utilise le théorème maître, méthode absente de la correction. Faut-il l'accepter comme réponse alternative valide ?",
            status="PENDING", related_entity_type="Question", related_entity_id=qid("Complexité des algorithmes de tri", 1), severity="blocking",
            proposed_answer="Accepter : le raisonnement est correct et distinct de celui de la correction.", criterion_id="1.2",
            comparative_clarification_kind="alternative_answer", submission_id=anas[0], created_at="2026-09-18 11:00+00", updated_at="2026-09-18 11:00+00"),
            casts={"status": "clarification_status", "severity": "clarification_severity", "comparative_clarification_kind": "comparative_clarification_kind", "created_at": "timestamptz", "updated_at": "timestamptz"})

        # ---------------- Arbitrages de contestations d'extraction ----------------
        blocs = await q(s, """select x.id, x.prediction_ocr, x.submission_id from extraction_corrections x join submissions su on su.id=x.submission_id
                              where su.exercise_id = any(:ids) and x.content_type='EQUATION' and x.human_correction is null order by x.created_at limit 200""", ids=[e[0] for e in exs])
        step = max(1, len(blocs) // 6)
        picks = [blocs[i * step + 1] for i in range(5)]
        for i, (xid, pred, _sub) in enumerate(picks):
            digits = [c for c in pred if c.isdigit()]
            claimed = pred.replace(digits[0], str(int(digits[0]) + 1), 1) if digits else pred
            resolved = i >= 3
            await s.execute(text("update extraction_corrections set contestation_type='content', contestation_status=CAST(:cs AS contestation_status), human_correction=:hc where id=:id"),
                            {"cs": "resolved" if resolved else "ambigu", "hc": claimed if i == 3 else None, "id": xid})
            await ins(s, "correction_arbitrations", dict(
                id=uuid.uuid4(), extraction_correction_id=xid, status="resolved" if resolved else "pending", claimed_correction=claimed,
                teacher_professor_id=karim if resolved else None, verdict=("accepted" if i == 3 else "rejected") if resolved else None,
                comment=("La lecture de l'étudiant est correcte après relecture de la copie." if i == 3 else "La lecture de l'OCR est fidèle à la copie : contestation rejetée.") if resolved else None,
                created_at="2026-09-19 10:00+00", updated_at="2026-09-19 10:00+00"),
                casts={"status": "arbitration_status", "verdict": "arbitration_verdict", "created_at": "timestamptz", "updated_at": "timestamptz"})

        # ---------------- Incidents ----------------
        student = {r[0]: r[1] for r in await q(s, "select first_name, id from users where email like '%@uca.com' and role='STUDENT'")}
        ex_id = {t: e for e, t, d, c in exs}
        inc = [
            ("Hamza", "Patrons de conception : Factory et Observer", "HEALTH", "Absent le jour du devoir (grippe) : certificat médical joint.", "PENDING", None, None, None),
            ("Meryem", "Intégration numérique : trapèzes et Simpson", "TECHNICAL", "Panne de connexion pendant le dépôt de la copie : le fichier n'a pas pu être envoyé avant la date limite.", "PENDING", None, None, None),
            ("Adam", "Interpolation polynomiale de Lagrange", "OTHER", "Convocation administrative le jour du devoir.", "PENDING", None, None, None),
            ("Nour", "Architecture en couches d'une application web", "HEALTH", "Hospitalisation la veille de l'examen.", "RESOLVED", "JUSTIFIED_ABSENCE", "Justificatif valide : absence excusée.", None),
            ("Ilyass", "Résolution d'équations non linéaires par la méthode de Newton", "TECHNICAL", "Ordinateur en panne pendant le dépôt.", "RESOLVED", "DEADLINE_EXTENDED", "Délai prolongé de 48 h.", "2026-09-22 18:00+00"),
        ]
        for fn, title, cat, reason, st, res, cmt, ext in inc:
            await ins(s, "submission_incidents", dict(
                id=uuid.uuid4(), exercise_id=ex_id[title], student_id=student[fn], reported_by_user_id=student[fn], category=cat,
                incident_occurred_at="2026-09-15 08:30+00", reason=reason, status=st, resolution=res,
                resolved_by_professor_id=karim if st == "RESOLVED" else None, resolution_comment=cmt,
                resolved_at="2026-09-17 16:00+00" if st == "RESOLVED" else None, extended_deadline=ext,
                created_at="2026-09-16 09:00+00", updated_at="2026-09-16 09:00+00"),
                casts={"category": "incident_category", "status": "incident_status", "resolution": "incident_resolution", "incident_occurred_at": "timestamptz",
                       "resolved_at": "timestamptz", "extended_deadline": "timestamptz", "created_at": "timestamptz", "updated_at": "timestamptz"})

        # ---------------- Recours de notes ----------------
        appeals = [("Omar", "Complexité des algorithmes de tri", 2, "PENDING", "Je conteste la note de la question 2 : ma justification de la complexité amortie est correcte et n'a pas été prise en compte.", 0.8, None, None),
                   ("Anas", "Complexité des algorithmes de tri", 1, "UNDER_REVIEW", "Le théorème maître est une méthode valide pour la question 1 : je demande une nouvelle lecture de ma réponse.", 0.6, None, None),
                   ("Hamza", "Patrons de conception : Factory et Observer", 1, "RESOLVED", "Le schéma de la sous-question 3.2 était bien présent sur ma copie.", 1.0, "GRADE_REVISED", "Schéma retrouvé sur la copie : sous-question 3.2 créditée.")]
        for fn, title, order, st, reason, delta, res, cmt in appeals:
            sid_ = next(x[0] for x in subs if x[4] == fn and x[1] == ex_id[title])
            ev = (await q(s, "select id, score from evaluations where submission_id=:sub and question_id=:qq", sub=sid_, qq=qid(title, order)))[0]
            orig = ev[1]
            await ins(s, "grade_appeals", dict(
                id=uuid.uuid4(), submission_id=sid_, evaluation_id=ev[0], student_id=student[fn], reason=reason, original_score=orig, status=st,
                resolution=res, revised_score=(orig + 1) if res else None, resolved_by_professor_id=karim if res else None, review_comment=cmt,
                resolved_at="2026-09-19 15:00+00" if res else None, ai_reevaluation_score=min(Decimal(10), orig + Decimal("0.8")),
                ai_reevaluation_justification="Réévaluation indépendante : la sous-question contestée est partiellement couverte, révision à la hausse proposée.",
                ai_reevaluation_criteria=[{"subquestion_id": "3.2", "completion_ratio": 0.67}],
                created_at="2026-09-18 12:00+00", updated_at="2026-09-18 12:00+00"),
                casts={"status": "appeal_status", "resolution": "appeal_resolution", "resolved_at": "timestamptz", "created_at": "timestamptz",
                       "updated_at": "timestamptz", "ai_reevaluation_criteria": "jsonb"})
        await s.commit()
        print(f"OK : {n_var} variantes (avec graphes), {n_log} journaux d'agents, 7 clarifications, 5 arbitrages, 5 incidents, 3 recours.")


asyncio.run(main())
