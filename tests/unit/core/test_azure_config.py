"""
Tests unitaires pour le garde-fou de configuration Azure Storage (Tâche 4).
Vérifie qu'une connection string vide ou incomplète lève une ValueError explicite.
"""
from unittest.mock import patch
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.infra_services.storage_service import StorageService


def test_settings_invalid_azure_connection_string_raises():
    """Vérifie que Settings lève une erreur si AZURE_STORAGE_CONNECTION_STRING ne contient pas AccountName/AccountKey."""
    invalid_strings = [
        "",
        "DefaultEndpointsProtocol=https;EndpointSuffix=core.windows.net",
        "AccountName=myaccount;",  # manque AccountKey
        "AccountKey=mykey;",       # manque AccountName
        "invalid_connection_string",
    ]

    for conn in invalid_strings:
        with pytest.raises((ValueError, ValidationError)) as exc_info:
            Settings(
                DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/test",
                REDIS_URL="redis://localhost:6379/0",
                AZURE_STORAGE_CONNECTION_STRING=conn,
                JWT_SECRET_KEY="secret",
            )
        assert "AZURE_STORAGE_CONNECTION_STRING est invalide ou incomplète" in str(exc_info.value)


def test_storage_service_get_client_invalid_connection_string_raises():
    """Vérifie que StorageService._get_client lève une ValueError explicite si la connection string est invalide."""
    service = StorageService()
    with patch("app.infra_services.storage_service.settings") as mock_settings:
        mock_settings.AZURE_STORAGE_CONNECTION_STRING = "invalid_string_without_account"
        with pytest.raises(ValueError) as exc_info:
            service._get_client()
        assert "AZURE_STORAGE_CONNECTION_STRING est invalide ou incomplète" in str(exc_info.value)
