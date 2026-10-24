"""
Service du bac à sable d'exécution (Judge0 API / sandbox local / Mock).
Utilisé par Comparative_Evaluation_Agent pour le mode TEST_CASE_BASED (§5).

Garantit :
1. Traçabilité explicite dans tools_consulted ("mock" vs "judge0_remote" vs
   "sandbox_local") pour ne jamais laisser croire à une vraie exécution qui
   n'a pas eu lieu, ni faire passer une exécution locale non isolée pour une
   exécution Judge0 (isolate) qu'elle n'est pas.
2. Un repli en cascade jamais bloquant : judge0_remote (si une clé API est
   configurée) → sandbox_local (défaut, aucune clé requise) → mock (filet de
   sécurité final si le sandbox local lui-même échoue techniquement).

Judge0 auto-hébergé (self-host) ÉCARTÉ (2026-09-10) : le sandbox `isolate`
que Judge0 utilise exige cgroup v1, absent de WSL2 (qui n'expose que
cgroup v2) — bug amont ouvert et non résolu (judge0/judge0#603, erreur
"Failed to create control group .../box-2/"), pas un problème de
configuration Docker qu'on peut corriger ici. `isolate` lui-même a ajouté le
support cgroup v2 en 2024, mais l'image `judge0/judge0` embarque encore une
version (1.8.1) antérieure à ce support.

sandbox_local (_execute_sandbox_local) — exécution réelle du code étudiant
en subprocess Python isolé du process courant, AVEC :
  - timeout mur (asyncio.wait_for) + limite CPU (RLIMIT_CPU sur POSIX)
  - limite mémoire virtuelle (RLIMIT_AS sur POSIX)
  - limite du nombre de processus/threads fils (RLIMIT_NPROC — anti fork-bomb)
  - répertoire de travail jetable, supprimé après exécution
  - `python -I -S` (mode isolé : ignore les variables d'environnement,
    désactive site-packages) — réduit l'accès aux dépendances installées
SANS (à la différence de Judge0/isolate) :
  - isolation réseau, filesystem (chroot/namespace) ou seccomp — le code
    étudiant tourne avec les mêmes permissions que le worker lui-même.
Containment de ressources et de crash, PAS une isolation de sécurité
complète face à un acteur réellement malveillant — jamais présenté comme
tel dans tools_consulted (execution_mode="sandbox_local", explicite).

judge0_remote (_execute_remote) — reste dans ce fichier, dormant : si une
JUDGE0_API_KEY (instance Judge0 CE hébergée, ex. RapidAPI) est un jour
configurée, ce chemin reprend la priorité sur sandbox_local automatiquement.
"""
import asyncio
import base64
import contextlib
from dataclasses import dataclass
import logging
import os
import shutil
import signal
import sys
import tempfile
import time
from typing import Literal

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

if os.name == "posix":
    import resource

# Judge0 CE — identifiants numériques de langage (cf. GET /languages de
# l'instance). Seul "python" est appelé aujourd'hui par Comparative_
# Evaluation_Agent (language="python" en dur, TEST_CASE_BASED §7), les
# autres entrées sont prêtes mais non exercées par le pipeline actuel.
_JUDGE0_LANGUAGE_IDS: dict[str, int] = {
    "python": 71,   # Python (3.8.1)
    "python3": 71,
    "c": 50,        # C (GCC 9.2.0)
    "cpp": 54,      # C++ (GCC 9.2.0)
    "java": 62,     # Java (OpenJDK 13.0.1)
    "javascript": 63,  # JavaScript (Node.js 12.14.0)
}

# Statuses Judge0 dont l'id signifie une exécution encore en cours au moment
# de la lecture de la réponse (In Queue=1, Processing=2) — ne devraient
# normalement jamais apparaître avec wait=true (synchrone), gardés ici
# uniquement pour détecter un comportement inattendu de l'API distante sans
# lever une exception opaque.
_JUDGE0_STATUS_ACCEPTED = 3


@dataclass
class TestCaseRunResult:
    input_data: str
    expected_output: str
    actual_output: str
    passed: bool
    visibility: Literal["visible", "hidden"]
    execution_time_ms: int | None = None
    status_description: str = "Accepted"
    execution_mode: Literal["mock", "judge0_remote", "sandbox_local"] = "mock"


class Judge0SandboxService:
    """
    Client de bac à sable d'exécution pour les cas de test informatique.
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        api_host: str | None = None,
        use_mock: bool | None = None,
    ):
        self.api_url = (api_url or settings.JUDGE0_API_URL).rstrip("/")
        self.api_host = api_host or settings.JUDGE0_API_HOST
        self.api_key = api_key or settings.JUDGE0_API_KEY

        if use_mock is not None:
            self.use_mock = use_mock
        elif settings.JUDGE0_USE_MOCK is not None:
            self.use_mock = settings.JUDGE0_USE_MOCK
        else:
            # Exécution réelle par défaut désormais : sandbox_local (ci-dessous)
            # ne nécessite aucune clé/infra externe — Judge0 auto-hébergé est
            # écarté (cgroup v1 requis, absent de WSL2, cf. docstring module).
            self.use_mock = False

    async def execute_test_cases(
        self,
        source_code: str,
        language: str,
        test_cases: list[dict],  # list of {"input": str, "expected_output": str, "visibility": str}
        timeout_seconds: float = 2.0,
        memory_limit_mb: int = 128,
    ) -> tuple[Literal["mock", "judge0_remote", "sandbox_local"], list[TestCaseRunResult]]:
        """
        Exécute une suite de cas de test sur le code source fourni.

        Retourne un tuple :
          (mode_execution, liste_des_resultats)
        où mode_execution est "mock", "judge0_remote" ou "sandbox_local".

        Cascade de repli, jamais bloquante :
          judge0_remote (si JUDGE0_API_KEY configurée) → sandbox_local (défaut)
          → mock (filet de sécurité final).
        """
        if self.use_mock:
            logger.info("[Judge0SandboxService] Exécution des cas de test en MODE MOCK déterministe.")
            return "mock", self._execute_mock(source_code, test_cases)

        if self.api_key:
            try:
                logger.info("[Judge0SandboxService] Exécution distante sur l'API Judge0 : %s", self.api_url)
                results = await self._execute_remote(
                    source_code=source_code,
                    language=language,
                    test_cases=test_cases,
                    timeout_seconds=timeout_seconds,
                    memory_limit_mb=memory_limit_mb,
                )
                return "judge0_remote", results
            except Exception as exc:
                logger.warning(
                    "[Judge0SandboxService] Échec de l'API distante Judge0 (%s). Repli sur le sandbox local.",
                    exc,
                )

        try:
            logger.info("[Judge0SandboxService] Exécution locale (sandbox subprocess, isolation partielle).")
            results = await self._execute_sandbox_local(
                source_code=source_code,
                language=language,
                test_cases=test_cases,
                timeout_seconds=timeout_seconds,
                memory_limit_mb=memory_limit_mb,
            )
            return "sandbox_local", results
        except Exception as exc:
            logger.warning(
                "[Judge0SandboxService] Échec du sandbox local (%s). Basculement de sécurité en MODE MOCK.",
                exc,
            )
            return "mock", self._execute_mock(source_code, test_cases)

    def _execute_mock(
        self,
        source_code: str,
        test_cases: list[dict],
    ) -> list[TestCaseRunResult]:
        """
        Simulation déterministe en mode local / test :
        Si le code contient 'FAIL_<input>', le cas échoue.
        Sinon, l'output simulé correspond exactement à expected_output.
        """
        results: list[TestCaseRunResult] = []
        for tc in test_cases:
            inp = str(tc.get("input", "")).strip()
            exp = str(tc.get("expected_output", "")).strip()
            vis = tc.get("visibility", "visible")

            # Condition de simulation d'échec pour les tests unitaires
            if f"FAIL_{inp}" in source_code or "FAIL_ALL" in source_code or (vis == "hidden" and "FAIL_HIDDEN" in source_code):
                passed = False
                actual = f"Error or incorrect output for {inp}"
                status = "Wrong Answer"
            else:
                passed = True
                actual = exp
                status = "Accepted"

            results.append(
                TestCaseRunResult(
                    input_data=inp,
                    expected_output=exp,
                    actual_output=actual,
                    passed=passed,
                    visibility=vis,
                    execution_time_ms=12,
                    status_description=status,
                    execution_mode="mock",
                )
            )
        return results

    async def _execute_remote(
        self,
        source_code: str,
        language: str,
        test_cases: list[dict],
        timeout_seconds: float,
        memory_limit_mb: int,
    ) -> list[TestCaseRunResult]:
        """
        Soumet chaque cas de test à l'instance Judge0 CE distante (RapidAPI),
        un appel HTTP synchrone (wait=true) par cas de test — séquentiel, pas
        en parallèle, pour rester sous les quotas de débit d'un plan RapidAPI
        gratuit. Une exception ici (réseau, auth, timeout) remonte telle
        quelle à execute_test_cases(), qui bascule alors TOUT le lot en mode
        mock (cf. son try/except) — jamais un résultat partiellement distant/
        partiellement mocké pour le même appel.
        """
        if not self.api_key:
            raise ValueError(
                "JUDGE0_API_KEY non configurée — impossible d'appeler l'API Judge0 distante."
            )

        language_id = _JUDGE0_LANGUAGE_IDS.get(language.lower())
        if language_id is None:
            raise ValueError(f"Langage non supporté par l'intégration Judge0 : {language!r}")

        headers = {
            "content-type": "application/json",
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": self.api_host,
        }
        submit_url = f"{self.api_url}/submissions"

        results: list[TestCaseRunResult] = []
        async with httpx.AsyncClient(timeout=timeout_seconds + 15.0) as client:
            for tc in test_cases:
                inp = str(tc.get("input", ""))
                exp = str(tc.get("expected_output", ""))
                vis = tc.get("visibility", "visible")

                payload = {
                    "source_code": base64.b64encode(source_code.encode("utf-8")).decode("ascii"),
                    "language_id": language_id,
                    "stdin": base64.b64encode(inp.encode("utf-8")).decode("ascii"),
                    "expected_output": base64.b64encode(exp.encode("utf-8")).decode("ascii"),
                    "cpu_time_limit": timeout_seconds,
                    # Judge0 attend le memory_limit en KB, notre paramètre est en MB.
                    "memory_limit": memory_limit_mb * 1024,
                }

                response = await client.post(
                    submit_url,
                    params={"base64_encoded": "true", "wait": "true"},
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

                status = data.get("status") or {}
                status_id = status.get("id")
                status_description = status.get("description", "Unknown")

                stdout = self._decode_b64_field(data.get("stdout"))
                stderr = self._decode_b64_field(data.get("stderr"))
                compile_output = self._decode_b64_field(data.get("compile_output"))

                passed = status_id == _JUDGE0_STATUS_ACCEPTED
                actual_output = stdout.strip() if stdout else (stderr or compile_output or "").strip()

                exec_time_ms = None
                if data.get("time") is not None:
                    try:
                        exec_time_ms = round(float(data["time"]) * 1000)
                    except (TypeError, ValueError):
                        exec_time_ms = None

                results.append(
                    TestCaseRunResult(
                        input_data=inp.strip(),
                        expected_output=exp.strip(),
                        actual_output=actual_output,
                        passed=passed,
                        visibility=vis,
                        execution_time_ms=exec_time_ms,
                        status_description=status_description,
                        execution_mode="judge0_remote",
                    )
                )
        return results

    @staticmethod
    def _decode_b64_field(value: str | None) -> str:
        if not value:
            return ""
        try:
            return base64.b64decode(value).decode("utf-8", errors="replace")
        except (ValueError, UnicodeDecodeError):
            return value

    # ------------------------------------------------------------------
    # sandbox_local — exécution réelle sans Judge0 (cf. docstring module)
    # ------------------------------------------------------------------

    # Seul "python" est réellement appelé aujourd'hui (Comparative_Evaluation_
    # Agent, language="python" en dur) — les autres langages du dict Judge0
    # (_JUDGE0_LANGUAGE_IDS) n'ont pas d'équivalent subprocess local ici.
    _SANDBOX_LOCAL_SUPPORTED_LANGUAGES = ("python", "python3")

    async def _execute_sandbox_local(
        self,
        source_code: str,
        language: str,
        test_cases: list[dict],
        timeout_seconds: float,
        memory_limit_mb: int,
    ) -> list[TestCaseRunResult]:
        if language.lower() not in self._SANDBOX_LOCAL_SUPPORTED_LANGUAGES:
            raise ValueError(f"Langage non supporté par le sandbox local : {language!r}")

        results: list[TestCaseRunResult] = []
        for tc in test_cases:
            inp = str(tc.get("input", ""))
            exp = str(tc.get("expected_output", "")).strip()
            vis = tc.get("visibility", "visible")

            actual, status_description, exec_time_ms = await self._run_python_subprocess(
                source_code, inp, timeout_seconds, memory_limit_mb,
            )
            actual = actual.strip()

            results.append(
                TestCaseRunResult(
                    input_data=inp.strip(),
                    expected_output=exp,
                    actual_output=actual,
                    passed=(status_description == "Accepted" and actual == exp),
                    visibility=vis,
                    execution_time_ms=exec_time_ms,
                    status_description=status_description,
                    execution_mode="sandbox_local",
                )
            )
        return results

    @staticmethod
    def _posix_resource_limits(memory_limit_mb: int, cpu_time_limit_seconds: int):
        """
        preexec_fn exécuté DANS le processus fils juste après fork(), avant
        exec() du code étudiant — RLIMIT_AS (mémoire virtuelle), RLIMIT_CPU
        (temps CPU, défense en profondeur en plus du timeout mur asyncio) et
        RLIMIT_NPROC (nombre de processus/threads fils, anti fork-bomb).
        POSIX uniquement (module `resource`, absent sous Windows nu).
        """
        def _apply() -> None:
            mem_bytes = memory_limit_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_time_limit_seconds, cpu_time_limit_seconds))
            resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
        return _apply

    async def _run_python_subprocess(
        self,
        source_code: str,
        stdin_data: str,
        timeout_seconds: float,
        memory_limit_mb: int,
    ) -> tuple[str, str, int | None]:
        """
        Exécute `source_code` dans un subprocess Python jetable : répertoire
        de travail temporaire (supprimé après coup, jamais l'arborescence de
        l'app), `-I -S` (mode isolé, pas de site-packages), stdin = l'input
        du cas de test, timeout mur strict via asyncio.wait_for (le process
        est tué s'il le dépasse). Ne lève jamais pour un échec du CODE
        ÉTUDIANT (retourne un statut "Runtime Error"/"Time Limit Exceeded"),
        seulement pour un échec TECHNIQUE du sandbox lui-même (répertoire non
        créable, etc.) — remonte alors à execute_test_cases() qui bascule en
        mock, même contrat que _execute_remote.
        """
        workdir = tempfile.mkdtemp(prefix="sandbox_local_")
        proc: asyncio.subprocess.Process | None = None
        try:
            preexec_fn = None
            if os.name == "posix":
                preexec_fn = self._posix_resource_limits(memory_limit_mb, max(1, int(timeout_seconds) + 1))

            t_start = time.perf_counter()
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-I", "-S", "-c", source_code,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
                preexec_fn=preexec_fn,
                # Groupe de processus dédié (POSIX uniquement — os.fork()
                # n'existe pas sous Windows, non applicable là-bas) : sans ça,
                # un fork-bomb étudiant (os.fork() en boucle) survit au kill
                # du timeout ci-dessous — proc.kill() ne tue QUE le process
                # direct, jamais les petits-enfants forkés. Incident réel
                # constaté le 2026-09-10 : un fork-bomb de test a rendu tout
                # le daemon Docker inutilisable malgré ce timeout, forçant un
                # wsl --shutdown pour récupérer — cause racine identifiée ici,
                # jamais un problème de RAM cette fois.
                start_new_session=(os.name == "posix"),
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(stdin_data.encode("utf-8")), timeout=timeout_seconds,
                )
                exec_time_ms = round((time.perf_counter() - t_start) * 1000)
                if proc.returncode == 0:
                    return stdout.decode("utf-8", errors="replace"), "Accepted", exec_time_ms
                error_text = stderr.decode("utf-8", errors="replace") or stdout.decode("utf-8", errors="replace")
                return error_text, "Runtime Error", exec_time_ms
            except asyncio.TimeoutError:
                return "", "Time Limit Exceeded", round(timeout_seconds * 1000)
        finally:
            # Tue tout le GROUPE de processus (jamais juste le PID direct) —
            # inconditionnel, même après une complétion normale : un fork
            # tardif juste avant la fin du process principal doit lui aussi
            # être nettoyé, pas seulement en cas de timeout.
            if proc is not None:
                self._kill_process_group(proc)
                with contextlib.suppress(ProcessLookupError):
                    await proc.wait()
            shutil.rmtree(workdir, ignore_errors=True)

    @staticmethod
    def _kill_process_group(proc: "asyncio.subprocess.Process") -> None:
        """POSIX : tue le groupe entier (os.killpg) — cf. start_new_session
        ci-dessus. Windows : os.fork() n'existe pas, un kill direct suffit."""
        with contextlib.suppress(ProcessLookupError, PermissionError):
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
