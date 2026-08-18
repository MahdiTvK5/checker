#!/usr/bin/env bash
#
# به‌روزرسانی روی سرور: آخرین کد را می‌گیرد و سرویس را ری‌استارت می‌کند.
# دیگر نیازی به دانلود/آپلود دستی نیست؛ فقط: ./update.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

echo "==> دریافت آخرین تغییرات از گیت"
git pull --ff-only

# shellcheck disable=SC1091
source venv/bin/activate

echo "==> به‌روزرسانی وابستگی‌ها"
if [ -n "${PIP_INDEX_URL:-}" ]; then
  pip install -i "$PIP_INDEX_URL" -r requirements.txt
else
  pip install -r requirements.txt
fi

echo "==> migrate و collectstatic"
python manage.py migrate --noinput
python manage.py collectstatic --noinput

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q '^checker.service'; then
  if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi
  echo "==> ری‌استارت سرویس"
  $SUDO systemctl restart checker
  echo "==> انجام شد ✅  (وضعیت: sudo systemctl status checker)"
else
  echo "==> به‌روزرسانی انجام شد ✅  سرویس را به‌صورت دستی ری‌استارت کنید."
fi
