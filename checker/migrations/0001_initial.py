from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Panel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(help_text="یک نام دلخواه برای شناسایی این پنل", max_length=100, verbose_name="نام پنل")),
                ("url", models.URLField(help_text="آدرس کامل پنل به همراه پورت و مسیر، مثال: http://1.2.3.4:54321/abcd", verbose_name="آدرس پنل")),
                ("username", models.CharField(max_length=100, verbose_name="نام کاربری")),
                ("password", models.CharField(max_length=255, verbose_name="رمز عبور")),
                ("verify_ssl", models.BooleanField(default=False, help_text="معمولاً پنل‌ها گواهی self-signed دارند؛ در آن صورت غیرفعال بماند.", verbose_name="بررسی گواهی SSL")),
                ("is_active", models.BooleanField(default=True, verbose_name="فعال")),
                ("order", models.PositiveIntegerField(default=0, help_text="پنل‌ها به ترتیب این عدد بررسی می‌شوند (کوچک‌تر زودتر).", verbose_name="ترتیب")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "پنل",
                "verbose_name_plural": "پنل‌ها",
                "ordering": ("order", "id"),
            },
        ),
    ]
