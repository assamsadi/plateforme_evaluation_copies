"""
Service de stockage de fichiers (Azure Blob Storage), en mode async.

Un seul service, importé à la fois par l'API (upload initial d'une copie,
génération d'URL pour le frontend) et par le worker (lecture pour OCR,
écriture des résultats). Le worker, natif sync côté Celery, appelle ce
service depuis l'intérieur du pipeline LangGraph déjà exécuté en async via
un unique `asyncio.run(...)` dans worker_main.py — pas de pont async/sync
ici, ce module reste 100% async.

Convention de nommage des blobs : préfixés par l'ID de l'entité propriétaire.
    submissions/{submission_id}/original.jpg
    submissions/{submission_id}/ocr_crops/{question_id}/{crop_id}.png
    exercises/{exercise_id}/teacher_correction.pdf
"""
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from azure.storage.blob.aio import BlobServiceClient
from azure.storage.blob import BlobSasPermissions, generate_blob_sas

from app.core.config import settings


class StorageContainer(StrEnum):
    """
    Noms de containers centralisés — à utiliser partout ailleurs dans le
    code plutôt que des strings en dur.
    """
    SUBMISSIONS = settings.AZURE_STORAGE_CONTAINER_SUBMISSIONS
    EXERCISES = settings.AZURE_STORAGE_CONTAINER_EXERCISES
    NOTEBOOKLM = settings.AZURE_STORAGE_CONTAINER_NOTEBOOKLM


# Durée de validité par défaut d'une URL signée (SAS). Les fichiers sont
# privés : toute consultation (ex. affichage frontend) passe par une URL
# temporaire générée à la demande, jamais par un accès public direct.
DEFAULT_SAS_EXPIRY_MINUTES = 15


class StorageService:
    def __init__(self) -> None:
        self._client = None

    def _get_client(self) -> BlobServiceClient:
        import asyncio
        current_loop = None
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        client_loop = getattr(self._client, "_loop", None) if self._client else None
        if self._client is None or (client_loop and client_loop.is_closed()) or (current_loop and client_loop and client_loop != current_loop and client_loop.is_closed()):
            conn_str = settings.AZURE_STORAGE_CONNECTION_STRING
            if not conn_str or "AccountName=" not in conn_str or "AccountKey=" not in conn_str:
                raise ValueError(
                    "AZURE_STORAGE_CONNECTION_STRING est invalide ou incomplète : "
                    "elle doit contenir au minimum 'AccountName=' et 'AccountKey='."
                )
            self._client = BlobServiceClient.from_connection_string(conn_str)
        return self._client

    async def close(self) -> None:
        """À appeler proprement à l'arrêt de l'API/du worker."""
        if self._client is not None:
            try:
                await self._client.close()
            finally:
                self._client = None

    async def upload(
        self,
        container: StorageContainer,
        blob_path: str,
        data: bytes,
        content_type: str | None = None,
        overwrite: bool = True,
    ) -> str:
        """
        Upload un fichier et retourne son blob_path (à persister en base,
        pas l'URL directement — l'URL se génère à la demande via
        `generate_read_url`, avec une expiration courte).
        """
        client = self._get_client()
        container_client = client.get_container_client(str(container))
        blob_client = container_client.get_blob_client(blob_path)

        content_settings = None
        if content_type:
            from azure.storage.blob import ContentSettings
            content_settings = ContentSettings(content_type=content_type)

        await blob_client.upload_blob(
            data,
            overwrite=overwrite,
            content_settings=content_settings,
        )
        return blob_path

    async def download(self, container: StorageContainer, blob_path: str) -> bytes:
        """Télécharge le contenu d'un blob (ex. pour l'OCR côté worker)."""
        client = self._get_client()
        container_client = client.get_container_client(str(container))
        blob_client = container_client.get_blob_client(blob_path)
        stream = await blob_client.download_blob()
        return await stream.readall()

    async def delete(self, container: StorageContainer, blob_path: str) -> None:
        client = self._get_client()
        container_client = client.get_container_client(str(container))
        blob_client = container_client.get_blob_client(blob_path)
        await blob_client.delete_blob()

    async def exists(self, container: StorageContainer, blob_path: str) -> bool:
        client = self._get_client()
        container_client = client.get_container_client(str(container))
        blob_client = container_client.get_blob_client(blob_path)
        return await blob_client.exists()

    async def find_blob_starting_with(self, container: StorageContainer, prefix: str) -> str | None:
        """Trouve le premier blob qui commence par un préfixe donné (évite de tester N extensions)."""
        client = self._get_client()
        container_client = client.get_container_client(str(container))
        # list_blobs renvoie un itérateur asynchrone
        async for blob in container_client.list_blobs(name_starts_with=prefix):
            return blob.name
        return None

    def generate_read_url(
        self,
        container: StorageContainer,
        blob_path: str,
        expiry_minutes: int = DEFAULT_SAS_EXPIRY_MINUTES,
    ) -> str:
        """
        Génère une URL signée (SAS), valable un temps limité, pour un accès
        en lecture seule — ex. le frontend affichant l'image scannée d'une
        copie sans jamais exposer le blob de façon permanente/publique.

        Synchrone : la génération de signature SAS ne fait aucun appel
        réseau (calcul cryptographique local), donc pas besoin d'async ici.
        """
        client = self._get_client()
        account_name = client.account_name
        account_key = client.credential.account_key

        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=str(container),
            blob_name=blob_path,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes),
        )
        return f"{client.url}{container}/{blob_path}?{sas_token}"


# Singleton, réutilisé par l'API et par le worker (chacun dans son propre
# process, même pattern que l'engine SQLAlchemy dans database.py).
storage_service = StorageService()