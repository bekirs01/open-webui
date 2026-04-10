#!/usr/bin/env bash
# İlk kurulum: Python venv, pip install -e ., npm install
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3.11}"
if ! command -v "$PY" &>/dev/null; then
	PY="python3"
fi

if [[ ! -d .venv ]]; then
	echo "→ venv oluşturuluyor ($PY)..."
	"$PY" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
echo "→ Python bağımlılıkları (pip install -e .)..."
pip install -U pip
pip install -e .

echo "→ npm install..."
npm install

echo ""
echo "Tamam. Geliştirme için: npm run dev:all"
echo "  Sadece arayüz: npm run dev:web"
echo "  Sadece API:   npm run dev:backend"
