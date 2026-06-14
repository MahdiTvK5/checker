from django.contrib import admin

from .models import Panel


@admin.register(Panel)
class PanelAdmin(admin.ModelAdmin):
    list_display = ("name", "url", "username", "is_active", "order", "updated_at")
    list_editable = ("is_active", "order")
    list_filter = ("is_active", "verify_ssl")
    search_fields = ("name", "url", "username")
    ordering = ("order", "id")
