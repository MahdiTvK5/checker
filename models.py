from django.db import models


class Panel(models.Model):
    """A single 3x-ui / X-UI panel that can be queried for config status.

    Multiple panels can be registered; a lookup is performed against every
    active panel until the requested config is found.
    """

    name = models.CharField(
        max_length=100,
        verbose_name="نام پنل",
        help_text="یک نام دلخواه برای شناسایی این پنل",
    )
    url = models.URLField(
        verbose_name="آدرس پنل",
        help_text="آدرس کامل پنل به همراه پورت و مسیر، مثال: http://1.2.3.4:54321/abcd",
    )
    username = models.CharField(max_length=100, verbose_name="نام کاربری")
    password = models.CharField(max_length=255, verbose_name="رمز عبور")
    verify_ssl = models.BooleanField(
        default=False,
        verbose_name="بررسی گواهی SSL",
        help_text="معمولاً پنل‌ها گواهی self-signed دارند؛ در آن صورت غیرفعال بماند.",
    )
    is_active = models.BooleanField(default=True, verbose_name="فعال")
    order = models.PositiveIntegerField(
        default=0,
        verbose_name="ترتیب",
        help_text="پنل‌ها به ترتیب این عدد بررسی می‌شوند (کوچک‌تر زودتر).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "پنل"
        verbose_name_plural = "پنل‌ها"
        ordering = ("order", "id")

    def __str__(self):
        return self.name

    @property
    def base_url(self):
        return self.url.rstrip("/")
