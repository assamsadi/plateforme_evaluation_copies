"""
Tests d'intégration du service de stockage Azure Blob Storage (Tâches 1 et 2).
Exécute de vraies opérations réseau contre le compte Azure configuré dans .env.
"""
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.infra_services.storage_service import StorageContainer, storage_service

pytestmark = [pytest.mark.azure_integration, pytest.mark.anyio]


@pytest.fixture(autouse=True)
async def cleanup_storage_client():
    yield
    await storage_service.close()


async def _run_container_crud_test(container: StorageContainer) -> None:
    """
    Helper générique pour la Tâche 1 :
    1. Upload d'un petit fichier texte factice (_healthcheck/{uuid}.txt).
    2. Vérification exists() -> True.
    3. Vérification download() -> contenu identique.
    4. Delete() -> vérification exists() -> False.
    Nettoyage garanti via try/finally.
    """
    unique_id = uuid.uuid4()
    blob_path = f"_healthcheck/{unique_id}.txt"
    test_content = f"Healthcheck content for container {container.value} - {unique_id}".encode("utf-8")

    try:
        # 1. Upload
        uploaded_path = await storage_service.upload(
            container=container,
            blob_path=blob_path,
            data=test_content,
            content_type="text/plain",
            overwrite=True,
        )
        assert uploaded_path == blob_path

        # 2. Exists -> True
        file_exists = await storage_service.exists(container=container, blob_path=blob_path)
        assert file_exists is True, f"Le blob {blob_path} devrait exister dans {container}"

        # 3. Download -> Contenu identique
        downloaded_content = await storage_service.download(container=container, blob_path=blob_path)
        assert downloaded_content == test_content

    finally:
        # 4. Delete & cleanup
        try:
            if await storage_service.exists(container=container, blob_path=blob_path):
                await storage_service.delete(container=container, blob_path=blob_path)
        except Exception:
            pass

    # Vérification après suppression
    post_delete_exists = await storage_service.exists(container=container, blob_path=blob_path)
    assert post_delete_exists is False, f"Le blob {blob_path} aurait dû être supprimé dans {container}"


async def test_azure_storage_crud_submissions_container() -> None:
    """Tâche 1 : Test CRUD complet sur le container SUBMISSIONS."""
    await _run_container_crud_test(StorageContainer.SUBMISSIONS)


async def test_azure_storage_crud_exercises_container() -> None:
    """Tâche 1 : Test CRUD complet sur le container EXERCISES."""
    await _run_container_crud_test(StorageContainer.EXERCISES)


async def test_azure_storage_sas_url_generation_and_validity() -> None:
    """
    Tâche 2 : Test de génération et validité d'URL SAS.
    1. Upload d'un fichier de test.
    2. Génération d'une URL SAS avec generate_read_url().
    3. Requête HTTP GET via httpx autonome pour vérifier le contenu et le code HTTP 200.
    4. Parsing de l'URL SAS pour vérifier la présence et la cohérence du paramètre 'se'.
    5. Test avec URL expirée (expiry_minutes=-5) -> Azure rejette avec HTTP 403 Forbidden.
    6. Nettoyage garanti.
    """
    unique_id = uuid.uuid4()
    blob_path = f"_healthcheck/sas_{unique_id}.txt"
    test_content = f"SAS URL test content {unique_id}".encode("utf-8")
    container = StorageContainer.SUBMISSIONS

    try:
        # 1. Upload
        await storage_service.upload(
            container=container,
            blob_path=blob_path,
            data=test_content,
            content_type="text/plain",
            overwrite=True,
        )

        # 2. Génération URL SAS (valide 15 minutes)
        expiry_minutes = 15
        sas_url = storage_service.generate_read_url(
            container=container,
            blob_path=blob_path,
            expiry_minutes=expiry_minutes,
        )
        assert sas_url.startswith("https://") or sas_url.startswith("http://")

        # 3. Accès HTTP GET autonome via httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(sas_url)
            assert response.status_code == 200
            assert response.content == test_content

        # 4. Vérification de la structure et du paramètre 'se' (Signed Expiry) dans le token SAS
        parsed_url = urlparse(sas_url)
        query_params = parse_qs(parsed_url.query)
        assert "se" in query_params, "Le token SAS doit contenir le paramètre d'expiration 'se'"

        se_str = query_params["se"][0]
        if se_str.endswith("Z"):
            se_str = se_str[:-1] + "+00:00"
        expiry_dt = datetime.fromisoformat(se_str)

        expected_expiry = datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes)
        diff_seconds = abs((expiry_dt - expected_expiry).total_seconds())
        assert diff_seconds < 120, f"La date d'expiration SAS ({expiry_dt}) s'écarte trop de la date attendue ({expected_expiry})"

        # 5. Vérification qu'une URL SAS expirée est rejetée (expiry_minutes = -5)
        expired_sas_url = storage_service.generate_read_url(
            container=container,
            blob_path=blob_path,
            expiry_minutes=-5,
        )
        async with httpx.AsyncClient() as client:
            expired_response = await client.get(expired_sas_url)
            assert expired_response.status_code == 403, (
                f"L'URL SAS expirée aurait dû retourner HTTP 403, obtenu {expired_response.status_code}"
            )

    finally:
        # Nettoyage garanti
        try:
            if await storage_service.exists(container=container, blob_path=blob_path):
                await storage_service.delete(container=container, blob_path=blob_path)
        except Exception:
            pass
