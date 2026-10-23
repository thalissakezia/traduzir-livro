"""Atualiza a execução do tradutor sem pedir que o usuário mate processos manualmente.

Execute após git pull: python .devcontainer/restart.py
Somente encerra processos Python "app.py" do Traduzir Livro.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.getenv("PORT", "7860"))
APP = ROOT / "app.py"
LOG = Path("/tmp/traduzir-livro.log")


def is_our_server(pid: int) -> bool:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        args = [x.decode(errors="replace") for x in raw.split(b"\0") if x]
        if not args or not any(Path(arg).name == "app.py" for arg in args[1:]):
            return False
        current = Path(f"/proc/{pid}/cwd").resolve()
        return current == ROOT or current == Path("/app") or any(
            arg == "/app/app.py" or arg == str(APP) for arg in args[1:]
        )
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return False


def health() -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{PORT}/health", timeout=2
        ) as reply:
            return reply.status == 200
    except (OSError, urllib.error.URLError):
        return False


def main() -> int:
    if not APP.is_file():
        print("Arquivo app.py não encontrado.", flush=True)
        return 1
    me = os.getpid()
    found = []
    for path in Path("/proc").iterdir():
        if path.name.isdigit():
            pid = int(path.name)
            if pid != me and is_our_server(pid):
                found.append(pid)

    print(f"Encerrando {len(found)} instância(s) antiga(s)...", flush=True)
    for pid in found:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    time.sleep(1.5)
    for pid in found:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    with LOG.open("w", encoding="utf-8") as out:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(APP)], cwd=str(ROOT),
            stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
            start_new_session=True
        )
    print(f"Inicializando nova interface na porta {PORT}...", flush=True)
    for _ in range(60):
        if proc.poll() is not None:
            print("Falha ao iniciar o tradutor. Diagnóstico:", flush=True)
            print(LOG.read_text(errors="replace")[-4000:], flush=True)
            return 1
        if health():
            print(f"✅ Tradutor atualizado e respondendo na porta {PORT}.", flush=True)
            print("Abra o endereço da porta no painel PORTAS.", flush=True)
            return 0
        time.sleep(1)
    print("O servidor não respondeu. Registro:", flush=True)
    print(LOG.read_text(errors="replace")[-4000:], flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
