from rest_framework import serializers

from .models import Company, Contact


class CompanySummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ("id", "name", "domain", "logo_url", "plan")


class ContactSummarySerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    email_verified = serializers.SerializerMethodField()
    company_detail = CompanySummarySerializer(source="company", read_only=True)

    class Meta:
        model = Contact
        fields = (
            "id",
            "display_name",
            "name",
            "email",
            "email_verified",
            "declared_email",
            "avatar_url",
            "company_detail",
            "is_anonymized",
        )

    def get_email_verified(self, obj) -> bool:
        return obj.email_verified_at is not None
