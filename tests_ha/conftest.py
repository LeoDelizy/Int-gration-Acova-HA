"""Tests d'intégration Home Assistant (pytest-homeassistant-custom-component).

À lancer séparément des tests purs : python -m pytest tests_ha -o asyncio_mode=auto
"""
import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
