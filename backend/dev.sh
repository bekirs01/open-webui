export CORS_ALLOW_ORIGIN="http://localhost:4000;http://localhost:2000"
PORT="${PORT:-2000}"
uvicorn open_webui.main:app --port $PORT --host 0.0.0.0 --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" --reload
