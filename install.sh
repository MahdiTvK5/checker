#!/usr/bin/env bash
#
# نصب و راه‌اندازی خودکار روی سرور (مخصوص اوبونتو/دبیان).
# استفاده:
#   git clone <repo> checker && cd checker
#   ./install.sh
#
# گزینه‌های اختیاری از طریق متغیر محیطی:
#   PIP_INDEX_URL=<میرور-pip-ایرانی>   برای نصب وابستگی‌ها از میرور داخلی
#   INSTALL_SERVICE=no                  برای رد کردن نصب سرویس systemd
#   SERVICE_USER=<user>                 کاربری که سرویس با آن اجرا شود
#   DJANGO_SUPERUSER_USERNAME / DJANGO_SUPERUSER_PASSWORD  ساخت خودکار ادمین
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"
PYTHON="${PYTHON:-python3}"

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

echo "==> نصب در مسیر: $APP_DIR"

# 1) پیش‌نیازهای سیستمی
if command -v apt-get >/dev/null 2>&1; then
  echo "==> نصب پیش‌نیازهای سیستمی (python3-venv, pip, git)"
  $SUDO apt-get update -y || true
  $SUDO apt-get install -y python3 python3-venv python3-pip git || true
fi

# 2) محیط مجازی
if [ ! -d venv ]; then
  echo "==> ساخت محیط مجازی (venv)"
  "$PYTHON" -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate

# 3) وابستگی‌ها (با امکان میرور ایرانی)
echo "==> نصب وابستگی‌های پایتون"
pip install --upgrade pip
if [ -n "${PIP_INDEX_URL:-}" ]; then
  echo "    استفاده از میرور: $PIP_INDEX_URL"
  pip install -i "$PIP_INDEX_URL" -r requirements.txt
else
  pip install -r requirements.txt
fi

# 4) فایل .env
if [ ! -f .env ]; then
  echo "==> ساخت فایل .env و کلید امنیتی تصادفی"
  cp .env.example .env
  SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(50))')"
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" .env
  echo "    فایل .env ساخته شد؛ در صورت نیاز ALLOWED_HOSTS را ویرایش کنید."
fi

# 5) دیتابیس و فایل‌های استاتیک
echo "==> اجرای migrate و collectstatic"
python manage.py migrate --noinput
python manage.py collectstatic --noinput

# 6) ساخت کاربر ادمین (اختیاری)
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  echo "==> ساخت کاربر ادمین: $DJANGO_SUPERUSER_USERNAME"
  DJANGO_SUPERUSER_EMAIL="${DJANGO_SUPERUSER_EMAIL:-admin@example.com}" \
    python manage.py createsuperuser --noinput \
    --username "$DJANGO_SUPERUSER_USERNAME" \
    --email "${DJANGO_SUPERUSER_EMAIL:-admin@example.com}" 2>/dev/null \
    || echo "    (کاربر از قبل وجود دارد یا ساخته نشد)"
else
  echo "==> برای ساخت کاربر ادمین بعداً اجرا کنید: source venv/bin/activate && python manage.py createsuperuser"
fi

# 7) سرویس systemd
if [ "${INSTALL_SERVICE:-yes}" = "yes" ] && command -v systemctl >/dev/null 2>&1; then
  RUN_USER="${SERVICE_USER:-$(whoami)}"
  echo "==> نصب سرویس systemd با کاربر: $RUN_USER"
  TMP="$(mktemp)"
  sed -e "s|__DIR__|$APP_DIR|g" -e "s|__USER__|$RUN_USER|g" deploy/checker.service > "$TMP"
  $SUDO cp "$TMP" /etc/systemd/system/checker.service
  rm -f "$TMP"
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable checker
  $SUDO systemctl restart checker
  echo "==> سرویس راه‌اندازی شد. وضعیت: sudo systemctl status checker"
else
  echo "==> سرویس systemd نصب نشد. برای اجرای دستی: ./run.sh"
fi

echo ""
echo "==> نصب کامل شد ✅"
echo "    آدرس: http://<IP سرور>:$(grep -E '^GUNICORN_BIND=' .env | cut -d: -f2 || echo 8000)"
echo "    پنل مدیریت: http://<IP سرور>:PORT/admin  (پنل‌ها را از اینجا اضافه کنید)"
