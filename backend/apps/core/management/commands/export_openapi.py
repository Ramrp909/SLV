"""Management command to export the OpenAPI schema to docs/openapi.json."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand
from drf_spectacular.generators import SchemaGenerator


class Command(BaseCommand):
    """Export the generated OpenAPI schema to a JSON file."""

    help = "Export the OpenAPI schema to docs/openapi.json"

    def handle(self, *args, **options):
        generator = SchemaGenerator()
        schema = generator.get_schema(request=None, public=True)

        docs_dir = settings.BASE_DIR.parent / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        out_path = docs_dir / "openapi.json"
        out_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")

        self.stdout.write(self.style.SUCCESS(f"Wrote OpenAPI schema to {out_path}"))
