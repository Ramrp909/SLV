"""OpenAPI schema, handler500 and route coverage tests."""

import json
import re
from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.http import HttpRequest, JsonResponse
from django.test import TestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver
from drf_spectacular.generators import SchemaGenerator

from common.errors import INTERNAL_ERROR
from config.urls import api_500_view

OPENAPI_PATH = settings.BASE_DIR.parent / "docs" / "openapi.json"


def _collect_routes(patterns, prefix=""):
    """Recursively collect every route string from a URLConf."""
    routes = []
    for pattern in patterns:
        route = getattr(pattern.pattern, "_route", None)
        if route is None:
            continue
        full = prefix + route
        if isinstance(pattern, URLResolver):
            routes.extend(_collect_routes(pattern.url_patterns, full))
        elif isinstance(pattern, URLPattern):
            routes.append(full)
    return routes


def _route_to_openapi_path(route):
    """Convert a Django route like 'api/v1/x/<int:pk>/' to '/api/v1/x/{}/'."""
    return "/" + re.sub(r"<[^>]*>", "{}", route)


def _normalize_path(path):
    """Normalize path parameters so {pk} and {id} compare equal."""
    return re.sub(r"\{[^}]*\}", "{}", path)


class TestHandler500(TestCase):
    def test_api_path_returns_standard_json_when_debug_false(self):
        with override_settings(DEBUG=False):
            request = HttpRequest()
            request.path = "/api/v1/invoices/"
            response = api_500_view(request)
        self.assertEqual(response.status_code, 500)
        self.assertIsInstance(response, JsonResponse)
        data = json.loads(response.content.decode("utf-8"))
        self.assertEqual(data["code"], INTERNAL_ERROR)
        self.assertEqual(data["message"], "An unexpected error occurred")
        self.assertEqual(data["fields"], {})

    def test_non_api_path_keeps_django_default_when_debug_false(self):
        with override_settings(DEBUG=False):
            request = HttpRequest()
            request.path = "/admin/"
            response = api_500_view(request)
        self.assertEqual(response.status_code, 500)
        self.assertNotIsInstance(response, JsonResponse)


class TestExportOpenApi(TestCase):
    def test_export_openapi_writes_valid_json(self):
        call_command("export_openapi")
        self.assertTrue(OPENAPI_PATH.exists(), f"missing {OPENAPI_PATH}")
        data = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
        self.assertIn("openapi", data)
        self.assertIn("paths", data)
        self.assertIn("components", data)


class TestRouteCoverage(TestCase):
    def test_every_api_v1_route_appears_in_openapi_schema(self):
        generator = SchemaGenerator()
        schema = generator.get_schema(request=None, public=True)
        schema_paths = set(schema.get("paths", {}).keys())

        root_resolver = get_resolver()
        routes = _collect_routes(root_resolver.url_patterns)
        api_routes = [r for r in routes if r.startswith("api/v1/")]
        self.assertTrue(api_routes, "no /api/v1/ routes found in URLConf")

        missing = []
        schema_normalized = {_normalize_path(p) for p in schema_paths}
        for route in api_routes:
            openapi_path = _route_to_openapi_path(route)
            if _normalize_path(openapi_path) not in schema_normalized:
                missing.append((route, openapi_path))
        self.assertFalse(
            missing,
            "Routes missing from OpenAPI schema:\n"
            + "\n".join(f"{route} -> {path}" for route, path in missing),
        )

    def test_all_api_v1_paths_end_with_slash(self):
        generator = SchemaGenerator()
        schema = generator.get_schema(request=None, public=True)
        schema_paths = set(schema.get("paths", {}).keys())
        api_paths = [p for p in schema_paths if p.startswith("/api/v1/")]
        self.assertTrue(api_paths, "no /api/v1/ paths in schema")
        bad = [p for p in api_paths if not p.endswith("/")]
        self.assertFalse(bad, f"paths missing trailing slash: {bad}")

    def test_spectacular_validate_passes(self):
        out = StringIO()
        call_command("spectacular", "--validate", "--fail-on-warn", stdout=out)
        self.assertIn("openapi", out.getvalue())
