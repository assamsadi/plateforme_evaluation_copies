"""
Tests GET/PUT /admin/config/models, GET/PUT /admin/config/settings —
protégés par get_current_admin (mécanisme existant, réutilisé tel quel).
"""
import pytest


def _make_model_config_read(task_type="feedback_generation", is_overridden=False):
    return {
        "task_type": task_type, "provider": "groq", "model_name": "llama-3.3-70b-versatile",
        "timeout_seconds": 45, "temperature": 0.1, "max_tokens": None, "supports_vision": False,
        "is_overridden": is_overridden, "updated_at": None,
    }


def _make_setting_read(key="MAX_LLM_CALLS_PER_THREAD"):
    return {
        "key": key, "value_type": "int", "default_value": "30",
        "override_value": None, "effective_value": "30", "updated_at": None,
    }


@pytest.mark.anyio
async def test_get_model_configurations_as_admin_returns_200(admin_client, mock_model_config_service):
    mock_model_config_service.get_effective_config.return_value = [_make_model_config_read()]

    response = await admin_client.get("/api/v1/admin/config/models")

    assert response.status_code == 200
    assert len(response.json()) == 1
    mock_model_config_service.get_effective_config.assert_awaited_once()


@pytest.mark.anyio
async def test_get_model_configurations_requires_admin_role(student_client, mock_model_config_service):
    response = await student_client.get("/api/v1/admin/config/models")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_put_model_configuration_success(admin_client, mock_model_config_service):
    mock_model_config_service.update_model_config.return_value = _make_model_config_read(
        task_type="ocr_vision", is_overridden=True,
    )

    response = await admin_client.put(
        "/api/v1/admin/config/models/ocr_vision",
        json={"provider": "openai", "model_name": "gpt-4o", "timeout_seconds": 90},
    )

    assert response.status_code == 200
    assert response.json()["is_overridden"] is True
    mock_model_config_service.update_model_config.assert_awaited_once()


@pytest.mark.anyio
async def test_put_model_configuration_invalid_task_type_returns_422(admin_client, mock_model_config_service):
    response = await admin_client.put(
        "/api/v1/admin/config/models/not_a_real_task_type",
        json={"provider": "openai", "model_name": "gpt-4o", "timeout_seconds": 90},
    )

    assert response.status_code == 422
    mock_model_config_service.update_model_config.assert_not_awaited()


@pytest.mark.anyio
async def test_put_model_configuration_invalid_provider_returns_422(admin_client, mock_model_config_service):
    response = await admin_client.put(
        "/api/v1/admin/config/models/ocr_vision",
        json={"provider": "not_a_real_provider", "model_name": "gpt-4o", "timeout_seconds": 90},
    )

    assert response.status_code == 422
    mock_model_config_service.update_model_config.assert_not_awaited()


@pytest.mark.anyio
async def test_put_model_configuration_invalid_timeout_returns_422(admin_client, mock_model_config_service):
    response = await admin_client.put(
        "/api/v1/admin/config/models/ocr_vision",
        json={"provider": "openai", "model_name": "gpt-4o", "timeout_seconds": 0},
    )

    assert response.status_code == 422
    mock_model_config_service.update_model_config.assert_not_awaited()


@pytest.mark.anyio
async def test_put_model_configuration_requires_admin_role(student_client, mock_model_config_service):
    response = await student_client.put(
        "/api/v1/admin/config/models/ocr_vision",
        json={"provider": "openai", "model_name": "gpt-4o", "timeout_seconds": 90},
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_get_system_config_settings_as_admin_returns_200(admin_client, mock_system_config_service):
    mock_system_config_service.get_all_settings.return_value = [_make_setting_read()]

    response = await admin_client.get("/api/v1/admin/config/settings")

    assert response.status_code == 200
    assert len(response.json()) == 1
    mock_system_config_service.get_all_settings.assert_awaited_once()


@pytest.mark.anyio
async def test_get_system_config_settings_requires_admin_role(student_client, mock_system_config_service):
    response = await student_client.get("/api/v1/admin/config/settings")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_put_system_config_setting_success(admin_client, mock_system_config_service):
    mock_system_config_service.update_setting.return_value = _make_setting_read()

    response = await admin_client.put(
        "/api/v1/admin/config/settings/MAX_LLM_CALLS_PER_THREAD", json={"value": "50"},
    )

    assert response.status_code == 200
    mock_system_config_service.update_setting.assert_awaited_once_with("MAX_LLM_CALLS_PER_THREAD", "50")


@pytest.mark.anyio
async def test_put_system_config_setting_invalid_key_returns_400(admin_client, mock_system_config_service):
    mock_system_config_service.update_setting.side_effect = ValueError("Seuil non configurable : 'GROQ_API_KEY'")

    response = await admin_client.put(
        "/api/v1/admin/config/settings/GROQ_API_KEY", json={"value": "hacked"},
    )

    assert response.status_code == 400


@pytest.mark.anyio
async def test_put_system_config_setting_invalid_value_returns_400(admin_client, mock_system_config_service):
    mock_system_config_service.update_setting.side_effect = ValueError("Valeur invalide pour le type int")

    response = await admin_client.put(
        "/api/v1/admin/config/settings/MAX_LLM_CALLS_PER_THREAD", json={"value": "not-a-number"},
    )

    assert response.status_code == 400


@pytest.mark.anyio
async def test_put_system_config_setting_requires_admin_role(student_client, mock_system_config_service):
    response = await student_client.put(
        "/api/v1/admin/config/settings/MAX_LLM_CALLS_PER_THREAD", json={"value": "50"},
    )
    assert response.status_code == 403
