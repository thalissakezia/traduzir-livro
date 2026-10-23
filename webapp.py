"""Servidor do Traduzir Livro: upload fragmentado para evitar HTTP 413 no proxy."""
from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
import secrets
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import fitz
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from engine import ArgosTranslator, OllamaTranslator, SOURCE_LANGUAGES, process_pdf

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("TRADUZIR_DATA_DIR", "/tmp/traduzir-livro-jobs"))
CHUNK_SIZE = 256 * 1024  # Menor que limites comuns de nginx (1 MiB).
MAX_UPLOAD_SIZE = 320 * 1024 * 1024
MAX_STORED_BYTES = 700 * 1024 * 1024
MAX_SESSIONS = 4
MAX_PENDING = 3
TTL_SECONDS = 4 * 60 * 60
TRANSLATORS = {"Gratuito (Argos)": "argos", "IA local (Ollama)": "ollama"}

app = FastAPI(title="Traduzir Livro", docs_url=None, redoc_url=None)
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pdf-translate")
mutex = threading.RLock()


@dataclass
class Upload:
    uid: str
    secret_digest: str
    original_name: str
    size: int
    created_at: float = field(default_factory=time.time)
    next_index: int = 0
    bytes_received: int = 0
    phase: str = "enviando"
    progress: float = 0
    message: str = "Recebendo PDF em partes pequenas."
    pages: int | None = None
    result_name: str | None = None
    error: str | None = None

    @property
    def directory(self):
        return DATA_DIR / self.uid

    @property
    def original_path(self):
        return self.directory / "original.pdf"

    @property
    def output_path(self):
        return self.directory / "traduzido.pdf"


uploads: dict[str, Upload] = {}


class InitRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=220)
    size: int = Field(gt=0, le=MAX_UPLOAD_SIZE)


class JobRequest(BaseModel):
    source: str = "Inglês"
    layout: str = "conservador"
    ocr: str = "automatico"
    backend: str = "argos"
    model: str = "qwen2.5:7b"


def require_upload(uid: str, token: str) -> Upload:
    with mutex:
        item = uploads.get(uid)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if not item or not hmac.compare_digest(item.secret_digest, digest):
            raise HTTPException(status_code=404, detail="Envio não encontrado.")
        return item


def read_token(request: Request) -> str:
    return request.headers.get("X-Upload-Token", "")


def cleanup_expired():
    now = time.time()
    stale = []
    with mutex:
        for uid, item in list(uploads.items()):
            if now - item.created_at > TTL_SECONDS and item.phase not in {"traduzindo", "na fila"}:
                stale.append((uid, item.directory))
                del uploads[uid]
    for _, directory in stale:
        shutil.rmtree(directory, ignore_errors=True)


def public_status(item: Upload) -> dict:
    return {
        "phase": item.phase,
        "progress": round(item.progress, 2),
        "message": item.message,
        "bytes_received": item.bytes_received,
        "size": item.size,
        "pages": item.pages,
        "download_ready": item.phase == "concluido",
        "error": item.error,
    }


@app.get("/", response_class=HTMLResponse)
def homepage():
    return (APP_DIR / "web" / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health():
    with mutex:
        return {"status": "ok", "service": "Traduzir Livro",
                "active_jobs": sum(x.phase in {"traduzindo", "na fila"} for x in uploads.values())}


@app.post("/api/uploads")
def init_upload(payload: InitRequest):
    cleanup_expired()
    if not payload.filename.casefold().endswith(".pdf"):
        raise HTTPException(400, "Selecione um arquivo PDF.")
    with mutex:
        if len(uploads) >= MAX_SESSIONS:
            raise HTTPException(429, "Limite de envios simultâneos. Tente novamente depois.")
        stored = sum(x.size for x in uploads.values())
        if stored + payload.size > MAX_STORED_BYTES:
            raise HTTPException(507, "Espaço reservado esgotado. Tente novamente depois.")
        uid = secrets.token_hex(20)
        token = secrets.token_urlsafe(32)
        name = Path(payload.filename.replace("\\", "/")).name
        item = Upload(uid, hashlib.sha256(token.encode()).hexdigest(), name, payload.size)
        item.directory.mkdir(parents=True, exist_ok=False)
        item.original_path.touch()
        uploads[uid] = item
    return {"upload_id": uid, "token": token, "chunk_size": CHUNK_SIZE,
            "chunks": math.ceil(payload.size / CHUNK_SIZE)}


@app.post("/api/uploads/{uid}/chunks/{index}")
async def upload_chunk(uid: str, index: int, request: Request):
    item = require_upload(uid, read_token(request))
    if index < 0:
        raise HTTPException(400, "Índice de bloco inválido.")
    # Nunca permitir corpos grandes na aplicação, mesmo em modo público.
    buffer = bytearray()
    async for data in request.stream():
        buffer.extend(data)
        if len(buffer) > CHUNK_SIZE:
            raise HTTPException(413, "Bloco excede 256 KiB.")
    with mutex:
        if item.phase != "enviando":
            raise HTTPException(409, "Este envio não aceita mais blocos.")
        if index < item.next_index:
            return {"accepted": True, "next_index": item.next_index}
        if index != item.next_index:
            raise HTTPException(409, f"Bloco fora de ordem; esperado {item.next_index}.")
        expected = min(CHUNK_SIZE, item.size - item.bytes_received)
        if len(buffer) != expected:
            raise HTTPException(400, f"Bloco de tamanho incorreto: recebido {len(buffer)}, esperado {expected}.")
        with item.original_path.open("ab") as handle:
            handle.write(buffer)
        item.bytes_received += len(buffer)
        item.next_index += 1
        item.progress = (item.bytes_received / item.size) * 100
        return {"accepted": True, "next_index": item.next_index,
                "received": item.bytes_received}


@app.post("/api/uploads/{uid}/complete")
def complete_upload(uid: str, request: Request):
    item = require_upload(uid, read_token(request))
    with mutex:
        if item.phase == "pronto":
            return public_status(item)
        if item.phase != "enviando" or item.bytes_received != item.size:
            raise HTTPException(409, "Ainda existem partes do PDF que não chegaram.")
        try:
            with item.original_path.open("rb") as handle:
                first_bytes = handle.read(1024)
            if b"%PDF-" not in first_bytes:
                raise ValueError("O arquivo enviado não é um PDF válido.")
            with fitz.open(str(item.original_path)) as pdf:
                if pdf.needs_pass:
                    raise ValueError("PDF protegido por senha: desbloqueie antes de enviar.")
                if len(pdf) == 0 or len(pdf) > 850:
                    raise ValueError("Este projeto aceita entre 1 e 850 páginas.")
                item.pages = len(pdf)
        except Exception as exc:
            item.phase = "erro"
            item.error = f"Falha na validação do PDF: {exc}"
            raise HTTPException(422, item.error) from exc
        item.phase = "pronto"
        item.progress = 0
        item.message = f"PDF recebido: {item.pages} páginas. Pronto para traduzir."
        return public_status(item)


def worker(item: Upload, settings: JobRequest):
    try:
        with mutex:
            item.phase = "traduzindo"
            item.message = "Preparando mecanismo de tradução em português..."
            item.progress = 0
        if settings.backend == "argos":
            translator = ArgosTranslator(SOURCE_LANGUAGES[settings.source])
        else:
            translator = OllamaTranslator(settings.model)

        def update(page, total, phase):
            with mutex:
                item.progress = min(99, round(page / total * 100, 1)) if total else 0
                item.message = f"{phase}: página {page}/{total}"

        result = process_pdf(
            str(item.original_path), str(item.output_path), translator,
            source_lang=SOURCE_LANGUAGES[settings.source], layout=settings.layout,
            ocr_policy=settings.ocr, progress=update
        )
        with mutex:
            item.phase = "concluido"
            item.progress = 100
            item.message = (
                f"Concluído: {result.pages_original} páginas originais, "
                f"{result.pages_final} no PDF final. Imagens verificadas: "
                f"{'sim' if result.image_verified else 'não'}."
            )
            item.result_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(item.original_name).stem)[:70] + "-ptbr.pdf"
    except Exception as exc:
        with mutex:
            item.phase = "erro"
            item.error = f"{type(exc).__name__}: {str(exc)}"
            item.message = "Ocorreu um problema durante a tradução."
        try:
            item.output_path.unlink(missing_ok=True)
        except OSError:
            pass


@app.post("/api/uploads/{uid}/translate")
def start_job(uid: str, request: Request, settings: JobRequest):
    item = require_upload(uid, read_token(request))
    if settings.source not in SOURCE_LANGUAGES:
        raise HTTPException(422, "Idioma de origem desconhecido.")
    if settings.backend not in {"argos", "ollama"}:
        raise HTTPException(422, "Mecanismo de tradução não disponível.")
    if settings.layout not in {"conservador", "substituir"}:
        raise HTTPException(422, "Modo de preservação desconhecido.")
    if settings.ocr not in {"automatico", "sempre", "nunca"}:
        raise HTTPException(422, "Modo OCR desconhecido.")
    with mutex:
        if item.phase != "pronto":
            raise HTTPException(409, "O PDF não está pronto ou já está sendo traduzido.")
        if sum(x.phase in {"na fila", "traduzindo"} for x in uploads.values()) >= MAX_PENDING:
            raise HTTPException(429, "Fila de tradução cheia. Tente novamente depois.")
        item.phase = "na fila"
        item.message = "Na fila para tradução; nenhum novo upload é necessário."
        executor.submit(worker, item, settings)
        return public_status(item)


@app.get("/api/uploads/{uid}/status")
def job_status(uid: str, request: Request):
    item = require_upload(uid, read_token(request))
    with mutex:
        return public_status(item)


@app.get("/api/uploads/{uid}/download")
def download(uid: str, token: str):
    item = require_upload(uid, token)
    with mutex:
        if item.phase != "concluido" or not item.output_path.exists():
            raise HTTPException(404, "O livro traduzido ainda não está disponível.")
    return FileResponse(
        str(item.output_path), media_type="application/pdf",
        filename=item.result_name or "livro-traduzido-ptbr.pdf",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
    )


@app.exception_handler(HTTPException)
async def http_error_handler(_: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail},
                        headers={"Cache-Control": "no-store"})
