"""Shared pytest fixtures for the Paint Shop test suite.

Fixtures are function-scoped and clean up after themselves (yield + teardown
delete) so they never leave data behind. They are safe to use with
TransactionTestCase-based tests: Django flushes the database between
TransactionTestCase tests, and the teardown deletes the objects created within
the test.

Seeded rows (the single AppSettings row, pk=1, and the 0.00 GST rate) come from
migration apps/core/migrations/0002_create_default_settings_and_gst_rate.py. If
a TransactionTestCase flush removes them, call ensure_seed_data() from
testsupport.factories to recreate exactly those two rows.
"""

import secrets

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.core.models import AppSettings

User = get_user_model()


def pytest_collection_modifyitems(config, items):
    """Promote tests carrying the project ``db`` marker to ``django_db``.

    The project ``db`` marker is a category label meaning "needs the database".
    pytest-django gates database access behind its own ``django_db`` marker
    (or the ``db``/``transactional_db`` fixtures), so tests using the project
    ``db`` marker still require the test database to be set up. Promote them
    here so the ``db`` fixture used by the shared conftest fixtures works.
    Tests without the ``db`` marker (pure unit tests) get no database access.
    """
    for item in items:
        if item.get_closest_marker("db") is not None:
            item.add_marker(pytest.mark.django_db)


OWNER_USERNAME = "test_owner"
ACCEPTANCE_OWNER_USERNAME = "acceptance_owner"


@pytest.fixture
def owner_user(db):
    """Owner user with a fixed fake username and a secrets-generated password.

    Created in the test database only; deleted in teardown so nothing is left
    behind.
    """
    password = secrets.token_urlsafe(16)
    user = User.objects.create_user(username=OWNER_USERNAME, password=password)
    yield user
    User.objects.filter(username=OWNER_USERNAME).delete()


@pytest.fixture
def api_client(owner_user):
    """APIClient force-authenticated as owner_user for fast API tests (no login)."""
    client = APIClient()
    client.force_authenticate(owner_user)
    return client


@pytest.fixture
def auth_client(db):
    """APIClient that logs in through POST /api/v1/auth/login/ and sends the
    Bearer token, for acceptance tests that exercise the real auth flow.

    The owner user is deleted in teardown.
    """
    password = secrets.token_urlsafe(16)
    User.objects.create_user(username=ACCEPTANCE_OWNER_USERNAME, password=password)
    client = APIClient()
    response = client.post(
        "/api/v1/auth/login/",
        {"username": ACCEPTANCE_OWNER_USERNAME, "password": password},
        format="json",
    )
    assert response.status_code == 200, response.content
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
    yield client
    User.objects.filter(username=ACCEPTANCE_OWNER_USERNAME).delete()


@pytest.fixture
def default_settings(db):
    """Return the single AppSettings row."""
    return AppSettings.get_settings()
