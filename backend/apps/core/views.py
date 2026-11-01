from django.http import JsonResponse
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckView(APIView):
    """Health check endpoint - no authentication required."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"status": "ok"}, status=status.HTTP_200_OK)


def api_404_view(request, exception=None):
    """Return JSON 404 for API routes."""
    if request.path.startswith("/api/"):
        return JsonResponse(
            {
                "code": "NOT_FOUND",
                "message": "Not found",
                "fields": {},
            },
            status=404,
        )
    # For non-API paths, fall back to Django's default 404
    from django.shortcuts import render

    return render(request, "404.html", status=404)
