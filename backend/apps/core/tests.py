from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient


class HealthCheckTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_health_endpoint_returns_ok(self):
        """Test that GET /api/v1/health returns 200 OK with {'status': 'ok'}"""
        url = reverse("core:health-check")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_health_endpoint_no_auth_required(self):
        """Test that health endpoint does not require authentication"""
        url = reverse("core:health-check")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should not return 401 Unauthorized
        self.assertNotEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
