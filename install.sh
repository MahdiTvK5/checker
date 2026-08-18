#!/usr/bin/env bash
#
# نصب و راه‌اندازی خودکار روی سرور (مخصوص اوبونتو/دبیان).
# استفاده:
#   git clone <repo> checker && cd checker
#   ./install.sh
#
# گزینه‌های اختیاری از طریق متغیر محیطی:
#   PIP_INDEX_URL=<میرور-pip-ایرانی>   برای نصب وابستگی‌ها از میرور داخلی
#   CHECKER_PORT=8088                    پورت سرویس (اگر ندهید، موقع نصب می‌پرسد)
#   SERVICE_USER=<user>                 کاربری که سرویس با آن اجرا شود
#   DJANGO_SUPERUSER_USERNAME / DJANGO_SUPERUSER_PASSWORD  ساخت خودکار ادمین
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"
PYTHON="${PYTHON:-python3}"

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

echo "==> نصب در مسیر: $APP_DIR"

is_valid_port() {
  [[ "${1:-}" =~ ^[0-9]+$ ]] && [ "$1" -ge 1 ] && [ "$1" -le 65535 ]
}

port_in_use() {
  local p="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | grep -Eq ":${p}[[:space:]]"
    return $?
  fi
  if command -v netstat >/dev/null 2>&1; then
    netstat -ltn 2>/dev/null | grep -Eq ":${p}[[:space:]]"
    return $?
  fi
  return 1
}

ask_listen_port() {
  # غیرتعاملی: CHECKER_PORT=9080 ./install.sh
  REQUESTED_PORT="${CHECKER_PORT:-${PORT:-}}"
  if [ -n "${REQUESTED_PORT}" ]; then
    if ! is_valid_port "$REQUESTED_PORT"; then
      echo "خطا: پورت ${REQUESTED_PORT} نامعتبر است (باید 1 تا 65535 باشد)." >&2
      exit 1
    fi
    LISTEN_PORT="$REQUESTED_PORT"
    return
  fi
  if [ ! -t 0 ]; then
    echo "خطا: ترمینال تعاملی نیست. پورت را این‌طور مشخص کنید: CHECKER_PORT=9080 ./install.sh" >&2
    exit 1
  fi
  echo ""
  echo "==> پورت سرویس را وارد کنید"
  echo "    اگر سرویس دیگری روی 8000 دارید، پورت آزاد دیگری بگذارید (مثلاً 8088 یا 9000)."
  while true; do
    printf "    پورت: "
    read -r LISTEN_PORT || true
    LISTEN_PORT="${LISTEN_PORT//[[:space:]]/}"
    if ! is_valid_port "$LISTEN_PORT"; then
      echo "    پورت باید یک عدد بین 1 و 65535 باشد."
      continue
    fi
    if port_in_use "$LISTEN_PORT"; then
      echo "    پورت $LISTEN_PORT الان اشغال است. یکی دیگر انتخاب کنید."
      continue
    fi
    break
  done
}

ask_listen_port
echo "==> سرویس روی پورت ${LISTEN_PORT} بالا می‌آید"

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
  DETECTED_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  if [ -n "${DETECTED_IP:-}" ]; then
    sed -i "s|^ALLOWED_HOSTS=.*|ALLOWED_HOSTS=127.0.0.1,localhost,${DETECTED_IP}|" .env
    echo "    ALLOWED_HOSTS شامل آی‌پی سرور شد: ${DETECTED_IP}"
  else
    echo "    فایل .env ساخته شد؛ ALLOWED_HOSTS را با آی‌پی/دامنه سرور ویرایش کنید."
  fi
fi
if grep -qE '^GUNICORN_BIND=' .env; then
  sed -i "s|^GUNICORN_BIND=.*|GUNICORN_BIND=0.0.0.0:${LISTEN_PORT}|" .env
else
  echo "GUNICORN_BIND=0.0.0.0:${LISTEN_PORT}" >> .env
fi
echo "    GUNICORN_BIND=0.0.0.0:${LISTEN_PORT}"

# 5) دیتابیس و فایل‌های استاتیک
echo "==> اجرای migrate و collectstatic"
python manage.py migrate --noinput
python manage.py collectstatic --noinput

# 6) ساخت کاربر ادمین (اختیاری)
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  echo "==> ساخت کاربر ادمین: $DJANGO_SUPERUSER_USERNAME"
  export DJANGO_SUPERUSER_PASSWORD
  export DJANGO_SUPERUSER_USERNAME
  export DJANGO_SUPERUSER_EMAIL="${DJANGO_SUPERUSER_EMAIL:-admin@localhost}"
  python manage.py createsuperuser --noinput \
    || echo "    (کاربر از قبل وجود دارد یا ساخته نشد — لاگ بالا را ببینید)"
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
echo "    آدرس: http://<IP سرور>:${LISTEN_PORT}"
echo "    پنل مدیریت: http://<IP سرور>:${LISTEN_PORT}/admin"
echo "    سلامت سرویس: http://<IP سرور>:${LISTEN_PORT}/healthz"
