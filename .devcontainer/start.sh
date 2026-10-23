#!/usr/bin/env bash
# Startup com verificação: não ocultar falhas do Gradio.
set -Eeuo pipefail
PORT="${PORT:-7860}"
LOG="/tmp/traduzir-livro.log"
APP="/workspaces/traduzir-livro/app.py"
if [ ! -f "$APP" ]; then APP="/app/app.py"; fi
echo "[traduzir-livro] Conferindo porta ${PORT}..."
check_http() {
  python - "$PORT" <<'PY'
import sys, urllib.request
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/", timeout=2) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
}
if check_http; then
  echo "[traduzir-livro] Já responde HTTP 200 na porta ${PORT}."
  exit 0
fi
echo "[traduzir-livro] Iniciando python -u ${APP}"
nohup python -u "$APP" > "$LOG" 2>&1 < /dev/null &
APP_PID=$!
for attempt in $(seq 1 60); do
  if check_http; then
    echo "[traduzir-livro] OK: HTTP 200. Abra a porta ${PORT} no painel PORTAS."
    exit 0
  fi
  if ! kill -0 "$APP_PID" 2>/dev/null; then
    echo "[traduzir-livro] Falha ao iniciar. Log:"
    cat "$LOG"
    exit 1
  fi
  sleep 1
done
echo "[traduzir-livro] Tempo excedido: aplicativo não respondeu. Log:"
tail -n 100 "$LOG" || true
exit 1
