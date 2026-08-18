from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("checker", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="panel",
            name="password",
            field=models.TextField(verbose_name="رمز عبور"),
        ),
        migrations.AlterField(
            model_name="panel",
            name="url",
            field=models.URLField(
                help_text="آدرس کامل پنل به همراه پورت و مسیر، مثال: http://1.2.3.4:54321/abcd",
                max_length=500,
                verbose_name="آدرس پنل",
            ),
        ),
        migrations.AlterField(
            model_name="panel",
            name="order",
            field=models.PositiveIntegerField(
                default=0,
                help_text="اگر کانفیگ روی چند پنل پیدا شود، پنل با عدد کوچک‌تر نمایش داده می‌شود.",
                verbose_name="اولویت",
            ),
        ),
    ]
