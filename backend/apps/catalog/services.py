"""Services for catalog app: Company write operations with audit."""

from apps.core.services import AuditService


class CompanyService:
    """Write operations for Company with audit entries in the same transaction."""

    AUDIT_FIELDS = ["name", "phone", "address", "gstin", "notes", "is_local", "is_active"]

    @staticmethod
    def _actor(request):
        return getattr(request, "user", None)

    @staticmethod
    def _snapshot(instance, fields):
        return {field: getattr(instance, field) for field in fields}

    @classmethod
    def create_company(cls, serializer, request):
        """Create a company and record company.created audit entry."""
        instance = serializer.save()
        AuditService.record(
            action="company.created",
            entity_type="Company",
            entity_id=str(instance.pk),
            summary=f"Company created: {instance.name}",
            before=None,
            after=cls._snapshot(instance, cls.AUDIT_FIELDS),
            request=request,
            actor=cls._actor(request),
        )
        return instance

    @classmethod
    def update_company(cls, instance, serializer, request):
        """Update a company; record company.updated only if something changed."""
        validated_data = serializer.validated_data or {}
        if not validated_data:
            return serializer.save()

        before = cls._snapshot(instance, validated_data.keys())
        instance = serializer.save()
        after = cls._snapshot(instance, validated_data.keys())
        if before == after:
            return instance

        AuditService.record(
            action="company.updated",
            entity_type="Company",
            entity_id=str(instance.pk),
            summary=f"Company updated: {instance.name}",
            before=before,
            after=after,
            request=request,
            actor=cls._actor(request),
        )
        return instance

    @classmethod
    def deactivate_company(cls, instance, request):
        """Deactivate a company; repeat calls are no-ops without new audit entries."""
        before = {"is_active": instance.is_active}
        instance.is_active = False
        instance.save()
        if before["is_active"]:
            AuditService.record(
                action="company.deactivated",
                entity_type="Company",
                entity_id=str(instance.pk),
                summary=f"Company deactivated: {instance.name}",
                before=before,
                after={"is_active": False},
                request=request,
                actor=cls._actor(request),
            )
        return instance

    @classmethod
    def activate_company(cls, instance, request):
        """Activate a company; repeat calls are no-ops without new audit entries."""
        before = {"is_active": instance.is_active}
        instance.is_active = True
        instance.save()
        if not before["is_active"]:
            AuditService.record(
                action="company.activated",
                entity_type="Company",
                entity_id=str(instance.pk),
                summary=f"Company activated: {instance.name}",
                before=before,
                after={"is_active": True},
                request=request,
                actor=cls._actor(request),
            )
        return instance
