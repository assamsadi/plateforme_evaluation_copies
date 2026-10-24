"""
Fausses données d'extraction OCR (captures d'écran / soutenance).

- Copies étudiantes : lignes ExtractionCorrection (blocs lus par l'OCR, confiance,
  quelques lectures corrigées par l'étudiant) + images de crops "manuscrites" +
  un PDF de copie (Submission.document_path).
- Exercices : lignes TeacherCorrectionBlock (blocs de la correction du professeur)
  + images de crops + PDF de référence.

Nécessite scripts/seed_demo_data.py déjà exécuté. Aucun appel LLM.
Usage : PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_ocr_data.py
"""
import asyncio
import io
import random
import uuid
from concurrent.futures import ThreadPoolExecutor

import fitz
from azure.storage.blob import BlobServiceClient, ContentSettings
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import async_session_maker
from app.domain.models.assessment.exercise import Exercise
from app.domain.models.assessment.extraction_correction import (
    ExtractionContentType,
    ExtractionCorrection,
    ExtractionEvidenceLevel,
)
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.submission import Submission
from app.domain.models.assessment.teacher_correction_block import BlockEvidenceLevel, TeacherCorrectionBlock
from app.domain.models.identity.user import User

RNG = random.Random(4242)
INK = "C:/Windows/Fonts/Inkfree.ttf"
PRINT = "C:/Windows/Fonts/arial.ttf"

# (texte d'introduction, formule, conclusion) par (titre d'exercice, ordre de question) — ASCII pour la police manuscrite.
CONTENT = {
    "Complexité des algorithmes de tri": [
        ("Tri par insertion : pire cas, tableau trie en ordre inverse.", "T(n) = sum(i, i=1..n-1) = n(n-1)/2 = O(n^2)", "Tri fusion : T(n) = 2T(n/2) + n donc O(n log n)."),
        ("Tableau presque trie : le tri par insertion est adapte.", "T(n) = O(n + k) avec k inversions", "Plus rapide que le tri rapide dont le pire cas est O(n^2)."),
    ],
    "Arbres binaires de recherche": [
        ("On insere 50, puis 30 a gauche et 70 a droite.", "50 -> (30, 70) ; 30 -> (20, 40) ; 70 -> (60, 80)", "L'arbre obtenu est equilibre, de hauteur 2."),
        ("Suppression d'un noeud a deux fils : on le remplace par son successeur.", "successeur = min(sous-arbre droit)", "Complexite O(h) ou h est la hauteur de l'arbre."),
    ],
    "Listes chaînées, piles et files": [
        ("Pile avec liste chainee : la tete de liste est le sommet.", "empiler = O(1) ; depiler = O(1)", "Toutes les operations sont en temps constant."),
        ("Deux piles P1 et P2 : on empile dans P1, on defile depuis P2.", "cout amorti = O(1) par operation", "Chaque element est deplace au plus une fois."),
    ],
    "Architecture en couches d'une application web": [
        ("Couches : presentation, metier, acces aux donnees.", "requete -> controleur -> service -> depot -> base", "Chaque couche ne depend que de la couche inferieure."),
        ("Le couplage metier/donnees rend les tests difficiles.", "Service depend de l'interface Depot", "On injecte l'implementation : inversion de dependance."),
    ],
    "Patrons de conception : Factory et Observer": [
        ("Factory : NotificationFactory cree Email, SMS ou Push.", "creer(type) -> Notification", "Le client ne connait pas les classes concretes."),
        ("Observer : le modele notifie ses vues a chaque changement.", "modele.notifier() -> vue.mettre_a_jour()", "Les vues sont decouplees du modele."),
    ],
    "Diagrammes UML de composants et de déploiement": [
        ("Composants : API, ServiceFacturation, BaseDeDonnees.", "API --> ServiceFacturation --> BaseDeDonnees", "Interfaces requises et fournies indiquees."),
        ("Trois serveurs : web, applicatif, base de donnees.", "Web(443) -> App(8080) -> BD(5432)", "Separation pour la securite et la montee en charge."),
    ],
    "Résolution d'équations non linéaires par la méthode de Newton": [
        ("f(x) = x^2 - 2, f'(x) = 2x, x0 = 1.", "x1 = 1 - (1-2)/2 = 1,5 ; x2 = 1,4167", "Erreur : |x2 - racine(2)| = 0,0025."),
        ("Newton converge quadratiquement, la dichotomie lineairement.", "e(n+1) ~ C * e(n)^2 pour Newton", "Newton est plus rapide si x0 est proche de la racine."),
    ],
    "Interpolation polynomiale de Lagrange": [
        ("Points (0,1), (1,3) et (2,2).", "P(x) = 1 + 3,5x - 1,5x^2", "On verifie P(0)=1, P(1)=3 et P(2)=2."),
        ("Erreur d'interpolation avec trois points equidistants.", "|E(x)| <= M3/6 * |x(x - pi/2)(x - pi)|", "M3 = 1 pour sin(x), donc E <= 0,16."),
    ],
    "Intégration numérique : trapèzes et Simpson": [
        ("Trapezes avec n = 4, h = 0,25.", "I ~ h/2 [f0 + 2(f1+f2+f3) + f4] = 0,7430", "La valeur exacte est proche de 0,7468."),
        ("Simpson avec n = 4, h = 0,25.", "I ~ h/3 [f0 + 4(f1+f3) + 2f2 + f4] = 0,7469", "Simpson est plus precis que les trapezes."),
    ],
}


def render(text, ink=True):
    font = ImageFont.truetype(INK if ink else PRINT, 34 if ink else 30)
    w = int(font.getlength(text)) + 60
    img = Image.new("RGB", (w, 84), (250, 248, 240) if ink else (255, 255, 255))
    d = ImageDraw.Draw(img)
    if ink:
        for y in (42, 78):
            d.line([(0, y + 12), (w, y + 12 + RNG.randint(-1, 1))], fill=(214, 220, 232), width=1)
    d.text((28, 20 + (RNG.randint(-2, 2) if ink else 0)), text, font=font, fill=(24, 44, 150) if ink else (20, 20, 20))
    if ink:
        img = img.rotate(RNG.uniform(-0.8, 0.8), expand=True, fillcolor=(250, 248, 240))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue(), img


def make_pdf(pages):
    """pages : liste de (titre, [PIL images])"""
    doc = fitz.open()
    for title, images in pages:
        page = doc.new_page(width=595, height=842)
        page.insert_text((40, 50), title, fontsize=13, fontname="helv")
        y = 80
        for img in images:
            b = io.BytesIO()
            img.save(b, "PNG")
            h = min(70, 520 * img.height / img.width)
            page.insert_image(fitz.Rect(40, y, 555, y + h), stream=b.getvalue(), keep_proportion=True)
            y += h + 16
    return doc.tobytes()


async def main():
    uploads = []  # (container, blob_path, bytes, content_type)
    async with async_session_maker() as s:
        if (await s.execute(select(func.count()).select_from(ExtractionCorrection))).scalar_one() > 0:
            print("ABANDON : des données d'extraction existent déjà.")
            return
        karim = (await s.execute(select(User).where(User.email == "karim.benali@uca.com"))).scalar_one()
        exercises = (await s.execute(select(Exercise).where(
            Exercise.created_by_professor_id == karim.id, Exercise.title.in_(list(CONTENT))))).scalars().all()
        questions = {}
        for ex in exercises:
            qs = (await s.execute(select(Question).where(Question.exercise_id == ex.id).order_by(Question.order))).scalars().all()
            questions[ex.id] = qs

        # ---- Côté professeur : blocs de correction + PDF de référence ----
        n_teacher = 0
        for ex_i, ex in enumerate(exercises):
            idx, page_imgs = 0, []
            for qi, q in enumerate(questions[ex.id]):
                intro, formula, concl = CONTENT[ex.title][qi]
                blocks = [("TEXT", intro), ("EQUATION", formula), ("TEXT", concl), ("TEXT", "Reponse : " + concl)]
                for kind, text in blocks:
                    png, img = render(text, ink=False)
                    path = f"exercises/{ex.id}/ocr_crops/page_{qi + 1}_block_{idx}.png"
                    uploads.append(("exercises", path, png, "image/png"))
                    page_imgs.append((qi, img))
                    inferred = ex_i == 0 and qi == 1 and kind == "TEXT" and idx % 2 == 0
                    s.add(TeacherCorrectionBlock(
                        id=uuid.uuid4(), exercise_id=ex.id, question_id=q.id, image_crop_path=path,
                        content_type=ExtractionContentType(kind), raw_text=text,
                        structured_content={"latex": text} if kind == "EQUATION" else None,
                        evidence_level=BlockEvidenceLevel.CONTENT_MATCHED if inferred else BlockEvidenceLevel.LABEL_EXPLICITE,
                        justification=("Rattaché par le sens du contenu (plusieurs questions candidates)." if inferred
                                       else f"Rattaché par le label explicite « Question {q.order} »."),
                        page_number=qi + 1, block_order_index=idx, ocr_confidence=round(RNG.uniform(0.86, 0.99), 3)))
                    idx += 1
                    n_teacher += 1
            pdf_pages = [(f"{ex.title} - correction du professeur - question {qn + 1}", [im for q2, im in page_imgs if q2 == qn]) for qn in range(len(questions[ex.id]))]
            uploads.append(("exercises", f"exercises/{ex.id}/reference.pdf", make_pdf(pdf_pages), "application/pdf"))

        # ---- Côté étudiant : blocs OCR + PDF de copie ----
        subs = (await s.execute(select(Submission).where(Submission.exercise_id.in_([e.id for e in exercises])))).scalars().all()
        ex_by_id = {e.id: e for e in exercises}
        n_student = 0
        for sub in subs:
            ex = ex_by_id[sub.exercise_id]
            idx, page_imgs = 0, []
            for qi, q in enumerate(questions[ex.id]):
                intro, formula, concl = CONTENT[ex.title][qi]
                for kind, text in (("TEXT", f"Question {q.order}"), ("TEXT", intro), ("EQUATION", formula), ("TEXT", concl)):
                    noisy = RNG.random() < 0.12 and any(ch in text for ch in "1,lI")
                    shown = text.replace("1", "l", 1) if noisy else text
                    png, img = render(shown, ink=True)
                    path = f"submissions/{sub.id}/ocr_crops/page_{qi + 1}_block_{idx}.png"
                    uploads.append(("submissions", path, png, "image/png"))
                    page_imgs.append((qi, img))
                    r = RNG.random()
                    s.add(ExtractionCorrection(
                        id=uuid.uuid4(), submission_id=sub.id, question_id=q.id, image_crop_path=path,
                        content_type=ExtractionContentType(kind), prediction_ocr=shown,
                        structured_output={"latex": shown} if kind == "EQUATION" else None,
                        human_correction=text if noisy else None,
                        confidence_score=round(RNG.uniform(0.55, 0.72) if noisy else RNG.uniform(0.84, 0.99) - (0.04 if kind == "EQUATION" else 0), 3),
                        bounding_box={"x": 80, "y": 90 + (idx % 6) * 130, "width": 840, "height": 100},
                        evidence_level=(ExtractionEvidenceLevel.AMBIGU if r < 0.04 else
                                        ExtractionEvidenceLevel.CONTENU_VS_REFERENCE if r < 0.20 else
                                        ExtractionEvidenceLevel.LABEL_EXPLICITE),
                        page_number=qi + 1))
                    idx += 1
                    n_student += 1
            pdf_pages = [(f"Copie - {ex.title} - question {qn + 1}", [im for q2, im in page_imgs if q2 == qn]) for qn in range(len(questions[ex.id]))]
            uploads.append(("submissions", f"submissions/{sub.id}/original.pdf", make_pdf(pdf_pages), "application/pdf"))
            sub.document_path = f"submissions/{sub.id}/original.pdf"
            sub.document_mime_type = "application/pdf"

        await s.flush()
        svc = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)

        def up(item):
            container, path, data, ctype = item
            svc.get_blob_client(container=container, blob=path).upload_blob(
                data, overwrite=True, content_settings=ContentSettings(content_type=ctype))

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(up, uploads))
        await s.commit()
        print(f"OK : {n_teacher} blocs de correction, {n_student} blocs OCR de copies, {len(uploads)} fichiers envoyés sur Azure.")


asyncio.run(main())
