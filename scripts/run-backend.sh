#!/usr/bin/env bash
# Proje kökünden çağrılır: backend'i .venv içindeki Python ile başlatır.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -x "$ROOT/.venv/bin/python3" ]]; then
	echo "Hata: $ROOT/.venv yok veya python3 çalıştırılamıyor."
	echo "Önce bir kez kurulum: cd \"$ROOT\" && npm run bootstrap"
	exit 1
fi
export PATH="$ROOT/.venv/bin:$PATH"
cd "$ROOT/backend"
exec bash ./start.sh
