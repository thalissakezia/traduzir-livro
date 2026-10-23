"""Testes da interface de upload em partes e da porta 7860."""
from __future__ import annotations
import os
import socket
import subprocess
import sys
import time
import urllib.request

def test_interface_imports():
    from app import app
    assert app is not None

def test_http_server_starts():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "PORT": str(port)}
    proc = subprocess.Popen(
        [sys.executable, "-u", "app.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    try:
        last_error = None
        for _ in range(60):
            if proc.poll() is not None:
                output = proc.stdout.read()
                raise AssertionError(f"Servidor FastAPI morreu durante o início: {output[-3000:]}")
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/", timeout=2
                ) as result:
                    assert result.status == 200
                    return
            except (OSError, TimeoutError) as exc:
                last_error = exc
                time.sleep(0.5)
        raise AssertionError(f"Servidor não abriu porta {port}: {last_error}")
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
