from django import forms
from django.contrib import admin

from .models import Panel

admin.site.site_header = "مدیریت استعلام اشتراک"
admin.site.site_title = "استعلام"
admin.site.index_title = "پنل‌های X-UI را از اینجا اضافه کنید"


class PanelForm(forms.ModelForm):
    password = forms.CharField(
        label="رمز عبور",
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        required=False,
        help_text="هنگام ویرایش، خالی بگذارید تا رمز قبلی حفظ شود.",
    )

    class Meta:
        model = Panel
        fields = ("name", "url", "username", "password", "verify_ssl", "is_active", "order")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["password"].required = True
            self.fields["password"].help_text = ""

    def save(self, commit=True):
        raw = (self.cleaned_data.get("password") or "").strip()
        instance = super().save(commit=False)
        if instance.pk and not raw:
            instance.password = Panel.objects.get(pk=instance.pk).password
        elif raw:
            instance.password = raw
        if commit:
            instance.save()
            self.save_m2m()
        return instance


@admin.register(Panel)
class PanelAdmin(admin.ModelAdmin):
    form = PanelForm
    list_display = ("name", "url", "username", "is_active", "order", "updated_at")
    list_display_links = ("name", "url")
    list_editable = ("is_active", "order")
    list_filter = ("is_active", "verify_ssl")
    search_fields = ("name", "url", "username")
    ordering = ("order", "id")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("مشخصات", {"fields": ("name", "url", "order", "is_active")}),
        ("ورود به پنل", {"fields": ("username", "password", "verify_ssl")}),
        ("زمان", {"fields": ("created_at", "updated_at")}),
    )
