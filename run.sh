#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  Vision (Open WebUI) — установка + запуск одной командой
#
#  Использование:
#    chmod +x run.sh && ./run.sh        # установка + backend + frontend
#    ./run.sh --backend                 # только backend  (порт 2000)
#    ./run.sh --frontend                # только frontend (порт 4000)
#    ./run.sh --install                 # только установка (без запуска)
#
#  Требования: Node.js ≥18, Python ≥3.11, npm, pip
# ─────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# ── Цвета ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

# ── Аргументы ──
MODE="all"
case "${1:-}" in
  --backend)  MODE="backend"  ;;
  --frontend) MODE="frontend" ;;
  --install)  MODE="install"  ;;
  --help|-h)
    echo "Usage: ./run.sh [--backend|--frontend|--install|--help]"
    echo "  (no flag)    install deps + start backend & frontend"
    echo "  --backend    install deps + start only backend  (:2000)"
    echo "  --frontend   install deps + start only frontend (:4000)"
    echo "  --install    install deps only (no servers started)"
    exit 0 ;;
esac

# ═══════════════════════════════════════════════════════════
#  1. Проверка системных зависимостей
# ═══════════════════════════════════════════════════════════
info "Проверка системных зависимостей..."

command -v node  >/dev/null 2>&1 || fail "Node.js не найден. Установите: https://nodejs.org (≥18)"
command -v npm   >/dev/null 2>&1 || fail "npm не найден."

NODE_MAJOR=$(node -v | sed 's/v//' | cut -d. -f1)
if [ "$NODE_MAJOR" -lt 18 ]; then
  fail "Node.js ≥18 обязателен (текущая: $(node -v))"
fi

PY=""
for candidate in python3.11 python3.12 python3.13 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    ver=$("$candidate" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)
    if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
      PY="$candidate"
      break
    fi
  fi
done
[ -z "$PY" ] && fail "Python ≥3.11 не найден. Установите: brew install python@3.11"

ok "Node $(node -v), $PY $($PY --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')"

# ═══════════════════════════════════════════════════════════
#  2. Python venv + pip install
# ═══════════════════════════════════════════════════════════
if [[ ! -d "$ROOT/.venv" ]]; then
  info "Создаю виртуальное окружение (.venv)..."
  "$PY" -m venv "$ROOT/.venv"
  ok ".venv создано"
else
  ok ".venv уже существует"
fi

# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

INSTALLED_MARKER="$ROOT/.venv/.deps_installed"
if [[ ! -f "$INSTALLED_MARKER" ]]; then
  info "Установка Python зависимостей (pip install -e .) — первый раз, ~3-5 мин..."
  pip install -U pip --quiet
  pip install -e "$ROOT" --quiet
  touch "$INSTALLED_MARKER"
  ok "Python зависимости установлены"
else
  ok "Python зависимости уже установлены (для обновления: rm $INSTALLED_MARKER)"
fi

# ═══════════════════════════════════════════════════════════
#  3. npm install + pyodide
# ═══════════════════════════════════════════════════════════
if [[ ! -d "$ROOT/node_modules" ]]; then
  info "npm install — первый раз, ~1-2 мин..."
  npm install --silent
  ok "npm зависимости установлены"
else
  ok "node_modules уже существует"
fi

if [[ ! -f "$ROOT/static/pyodide/pyodide.js" ]]; then
  info "Подготовка Pyodide..."
  npm run pyodide:fetch --silent 2>/dev/null || node scripts/prepare-pyodide.js
  ok "Pyodide готов"
else
  ok "Pyodide уже подготовлен"
fi

# ═══════════════════════════════════════════════════════════
#  4. .env (если нет — копируем из примера)
# ═══════════════════════════════════════════════════════════
if [[ ! -f "$ROOT/.env" ]]; then
  if [[ -f "$ROOT/.env.example" ]]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
    warn ".env создан из .env.example — проверьте API ключи!"
  else
    warn ".env отсутствует и .env.example не найден"
  fi
else
  ok ".env на месте"
fi

# ═══════════════════════════════════════════════════════════
#  5. Запуск
# ═══════════════════════════════════════════════════════════
if [[ "$MODE" == "install" ]]; then
  echo ""
  ok "Установка завершена. Команды для запуска:"
  echo "   ./run.sh              — backend + frontend"
  echo "   ./run.sh --backend    — только backend  (http://127.0.0.1:2000)"
  echo "   ./run.sh --frontend   — только frontend (http://127.0.0.1:4000)"
  exit 0
fi

cleanup() {
  echo ""
  info "Остановка серверов..."
  kill "$BACKEND_PID" 2>/dev/null || true
  kill "$FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  ok "Серверы остановлены"
}
BACKEND_PID=""
FRONTEND_PID=""

start_backend() {
  info "Запуск backend (http://127.0.0.1:2000)..."
  export PATH="$ROOT/.venv/bin:$PATH"
  cd "$ROOT/backend"
  export CORS_ALLOW_ORIGIN="http://localhost:4000;http://localhost:2000"
  PORT="${PORT:-2000}" WEBUI_SECRET_KEY="${WEBUI_SECRET_KEY:-$(head -c 12 /dev/urandom | base64)}" \
    "$ROOT/.venv/bin/python3" -m uvicorn open_webui.main:app \
      --host 0.0.0.0 --port "${PORT:-2000}" \
      --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
      --reload &
  BACKEND_PID=$!
  cd "$ROOT"
}

start_frontend() {
  info "Запуск frontend (http://127.0.0.1:4000)..."
  cd "$ROOT"
  npx vite dev --host --port 4000 &
  FRONTEND_PID=$!
}

trap cleanup EXIT INT TERM

case "$MODE" in
  backend)
    start_backend
    echo ""
    ok "Backend запущен: http://127.0.0.1:2000"
    echo "   Ctrl+C для остановки"
    wait "$BACKEND_PID" 2>/dev/null
    ;;
  frontend)
    start_frontend
    echo ""
    ok "Frontend запущен: http://127.0.0.1:4000"
    echo "   Ctrl+C для остановки"
    wait "$FRONTEND_PID" 2>/dev/null
    ;;
  all)
    start_backend
    sleep 2
    start_frontend
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  ✓ Vision запущен!${NC}"
    echo -e "${GREEN}  Backend:  http://127.0.0.1:2000${NC}"
    echo -e "${GREEN}  Frontend: http://127.0.0.1:4000  ← открыть${NC}"
    echo -e "${GREEN}  Ctrl+C для остановки${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
    wait
    ;;
esac
