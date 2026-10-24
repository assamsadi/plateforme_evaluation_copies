# AI-Assisted Exam Grading Platform

A web platform that automates the correction of handwritten student exam papers with a pipeline of AI agents, while keeping the teacher in control (validation, arbitration, appeals).

## Features
- OCR extraction of scanned exam papers and structuring into questions / answers
- Automatic attachment of answers to questions and generation of reference solution variants
- Comparative evaluation against a grading scheme, with detailed per-sub-question judgments
- Competency assessment and student progress tracking
- Personalised feedback and recommended exercises
- Teacher validation, correction arbitration, grade appeals and integrity alerts
- Role-based access (admin / teacher / student), audit logs, multilingual UI
- LLM observability with Langfuse

## Architecture
- **Backend**: FastAPI (`app/api`), domain models and repositories (SQLAlchemy 2 + Alembic), JWT authentication
- **Agents**: one module per task in `app/agents` (OCR, structuring, attachment, comparison, feedback, recommendation…), orchestrated by a graph in `app/graph`
- **Async processing**: Celery workers with Redis / Redpanda for jobs and events
- **Frontend**: Next.js 16 + React 19 + Tailwind CSS 4 + next-intl (`frontend/`)
- **Infra**: Docker Compose (PostgreSQL, Redis, Redpanda, API, worker, frontend)

## Tech stack
Python · FastAPI · SQLAlchemy · Alembic · Celery · Redis · PostgreSQL · Groq / OpenAI LLMs · Langfuse · Next.js · React · TypeScript · Tailwind CSS · Docker

## Getting started
```bash
cp .env.example .env              # fill in your own keys
cp frontend/.env.example frontend/.env.local
docker compose up -d postgres redis redpanda
pip install -r requirements.txt
alembic upgrade head
python scripts/create_first_admin.py
uvicorn app.main:app --reload            # API on :8000
celery -A app.worker_main:celery_app worker --loglevel=info
cd frontend && pnpm install && pnpm dev  # UI on :3000
```
Optional demo data: `python scripts/seed_demo_data.py` (set `DEMO_PASSWORD` to choose the demo accounts' password).
Tests: `pytest`.

## Author
**Ahlam Assamsadi**: [Portfolio](https://ahlam-assamsadi.vercel.app) · [GitHub](https://github.com/assamsadi)

---

# Plateforme de correction de copies assistée par IA

Plateforme web qui automatise la correction de copies d'examen manuscrites grâce à une chaîne d'agents IA, tout en laissant l'enseignant maître de la décision (validation, arbitrage, contestations).

## Fonctionnalités
- Extraction OCR des copies scannées et structuration en questions / réponses
- Rattachement automatique des réponses aux questions et génération de variantes de solution
- Évaluation comparative selon un barème, avec jugements détaillés par sous-question
- Évaluation des compétences et suivi de la progression des étudiants
- Feedback personnalisé et exercices recommandés
- Validation enseignant, arbitrage des corrections, contestations de notes, alertes d'intégrité
- Accès par rôle (admin / enseignant / étudiant), journaux d'audit, interface multilingue
- Observabilité des appels LLM avec Langfuse

## Architecture
- **Backend** : FastAPI (`app/api`), modèles de domaine et dépôts (SQLAlchemy 2 + Alembic), authentification JWT
- **Agents** : un module par tâche dans `app/agents`, orchestrés par un graphe dans `app/graph`
- **Traitement asynchrone** : workers Celery avec Redis / Redpanda
- **Frontend** : Next.js 16 + React 19 + Tailwind CSS 4 + next-intl (`frontend/`)
- **Infra** : Docker Compose (PostgreSQL, Redis, Redpanda, API, worker, frontend)

## Technologies
Python · FastAPI · SQLAlchemy · Alembic · Celery · Redis · PostgreSQL · LLM Groq / OpenAI · Langfuse · Next.js · React · TypeScript · Tailwind CSS · Docker

## Installation et lancement
Voir la section *Getting started* ci-dessus : copier `.env.example` en `.env` avec vos propres clés, lancer l'infrastructure avec Docker Compose, appliquer les migrations Alembic, puis démarrer l'API, le worker Celery et le frontend.

## Auteure
**Ahlam Assamsadi** : [Portfolio](https://ahlam-assamsadi.vercel.app) · [GitHub](https://github.com/assamsadi)
