from django.core.signing import BadSignature, Signer
from django.db import models

_PASSWORD_PREFIX = "enc:"


def _password_signer():
    return Signer(salt="checker.panel.password")


def encrypt_password(raw):
    if not raw or str(raw).startswith(_PASSWORD_PREFIX):
        return raw
    return _PASSWORD_PREFIX + _password_signer().sign_object(raw)


def decrypt_password(stored):
    if not stored:
        return stored
    if not str(stored).startswith(_PASSWORD_PREFIX):
        return stored
    try:
        return _password_signer().unsign_object(stored[len(_PASSWORD_PREFIX):])
    except (BadSignature, ValueError, TypeError):
        return stored


class Panel(models.Model):
    """A single 3x-ui / X-UI panel that can be queried for config status."""

    name = models.CharField(
        max_length=100,
        verbose_name="نام پنل",
        help_text="یک نام دلخواه برای شناسایی این پنل",
    )
    url = models.URLField(
        max_length=500,
        verbose_name="آدرس پنل",
        help_text="آدرس کامل پنل به همراه پورت و مسیر، مثال: http://1.2.3.4:54321/abcd",
    )
    username = models.CharField(max_length=100, verbose_name="نام کاربری")
    password = models.TextField(verbose_name="رمز عبور")
    verify_ssl = models.BooleanField(
        default=False,
        verbose_name="بررسی گواهی SSL",
        help_text="معمولاً پنل‌ها گواهی self-signed دارند؛ در آن صورت غیرفعال بماند.",
    )
    is_active = models.BooleanField(default=True, verbose_name="فعال")
    order = models.PositiveIntegerField(
        default=0,
        verbose_name="اولویت",
        help_text="اگر کانفیگ روی چند پنل پیدا شود، پنل با عدد کوچک‌تر نمایش داده می‌شود.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "پنل"
        verbose_name_plural = "پنل‌ها"
        ordering = ("order", "id")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.password:
            self.password = encrypt_password(self.password)
        super().save(*args, **kwargs)

    @property
    def base_url(self):
        return (self.url or "").rstrip("/")

    @property
    def plain_password(self):
        return decrypt_password(self.password)
