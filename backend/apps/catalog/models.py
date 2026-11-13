"""Models for catalog app: Company (paint companies / suppliers / local group)."""

from common.errors import DUPLICATE_COMPANY_NAME
from common.validators import normalize_gstin, normalize_phone
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Value
from django.db.models.functions import Lower


def _normalise_name(value: str) -> str:
    """Trim and collapse repeated spaces in a company name."""
    return " ".join(str(value).split())


class Company(models.Model):
    """
    A paint company / supplier / local group.

    Company-wise stock, purchases, payments, dues, sales and profit are
    tracked per company (blueprint sections 7.3 and 15.5).

    The name is unique case-insensitively, enforced in the database with a
    functional unique constraint on lower(name), so "Berger" and "berger "
    are the same company.
    """

    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    gstin = models.CharField(max_length=15, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    is_local = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="unique_company_name_lower",
            ),
        ]
        indexes = [
            models.Index(fields=["is_active"]),
            models.Index(fields=["is_local"]),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.name:
            self.name = _normalise_name(self.name)
        if self.name:
            qs = Company.objects.annotate(ln=Lower("name")).filter(ln=Lower(Value(self.name)))
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    {"name": "Company with this name already exists."},
                    code=DUPLICATE_COMPANY_NAME,
                )

    def save(self, *args, **kwargs):
        if self.name:
            self.name = _normalise_name(self.name)
        if self.phone:
            self.phone = normalize_phone(self.phone)
        if self.gstin:
            self.gstin = normalize_gstin(self.gstin)
        super().save(*args, **kwargs)
