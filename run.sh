#!/usr/bin/env bash
#
# اجرای دستی سرور با gunicorn (بدون systemd) - برای تست یا اجرای ساده.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

# shellcheck disable=SC1091
source venv/bin/activate

# بارگذاری متغیرهای .env (با حذف \r در صورت ویرایش در ویندوز)
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1090
  . <(sed 's/\r$//' .env)
  set +a
fi

exec gunicorn config.wsgi:application \
  --bind "${GUNICORN_BIND:-0.0.0.0:8000}" \
  --workers "${GUNICORN_WORKERS:-3}"
