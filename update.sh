#!/usr/bin/env bash
#
# به‌روزرسانی روی سرور. هم با git کار می‌کند، هم اگر پوشه را دستی آپلود
# کرده باشید (بدون .git) آخرین zip را از GitHub می‌گیرد.
#
# فایل‌های .env و db.sqlite3 و venv دست نمی‌خورند.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

REPO_SLUG="${REPO_SLUG:-MahdiTvK5/checker}"
BRANCH="${CHECKER_BRANCH:-main}"

fetch_zip() {
  local url="https://github.com/${REPO_SLUG}/archive/refs/heads/${BRANCH}.zip"
  echo "==> این پوشه مخزن git نیست؛ دانلود از GitHub: ${BRANCH}"
  echo "    ${url}"
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$tmp/src.zip"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$tmp/src.zip" "$url"
  else
    echo "خطا: نه git هست، نه curl/wget. یکی را نصب کنید: apt-get install -y git curl unzip" >&2
    exit 1
  fi
  command -v unzip >/dev/null 2>&1 || { apt-get install -y unzip >/dev/null 2>&1 || true; }
  unzip -q "$tmp/src.zip" -d "$tmp"
  local src
  src="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -1)"
  if [ -z "$src" ]; then
    echo "خطا: zip خالی بود." >&2
    exit 1
  fi
  # کد جدید را روی پوشه فعلی می‌ریزیم؛ دادهٔ سرور حفظ می‌شود.
  command -v rsync >/dev/null 2>&1 || apt-get install -y rsync >/dev/null 2>&1 || true
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete \
      --exclude '.env' \
      --exclude 'db.sqlite3' \
      --exclude 'venv/' \
      --exclude 'staticfiles/' \
      --exclude '.git/' \
      "$src"/ "$APP_DIR"/
  else
    echo "خطا: rsync نصب نشد." >&2
    exit 1
  fi
  echo "==> فایل‌های کد به‌روز شد (.env و دیتابیس حفظ شدند)"
}

if [ -d .git ]; then
  echo "==> دریافت آخرین تغییرات از گیت"
  git pull --ff-only origin "${BRANCH}" || git pull --ff-only
else
  fetch_zip
fi

if [ ! -d venv ]; then
  echo "==> venv پیدا نشد. لطفاً یک‌بار ./install.sh را اجرا کنید."
  exit 1
fi

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
  $SUDO systemctl restart checker || $SUDO systemctl restart checker.service || true
  echo "==> انجام شد ✅  (وضعیت: systemctl status checker)"
else
  echo "==> کد به‌روز شد. اگر با run.sh/gunicorn دستی اجرا می‌کنید، یک‌بار ری‌استارت کنید."
fi
