"""Regressões: PDF maior que 1MB deve chegar sem POST único gigante."""
from __future__ import annotations

import io
import os
import time

import fitz
from fastapi.testclient import TestClient
from PIL import Image

import webapp
from engine import image_fingerprints


class TranslatorStub:
    def __init__(self, *args, **kwargs):
        pass

    def translate(self, text):
        return "Personagem traduzido: " + text


def make_large_pdf() -> bytes:
    # PNG ruidoso não é tão compactável: o PDF ultrapassa 1 MiB.
    picture = Image.frombytes("RGB", (740, 680), os.urandom(740 * 680 * 3))
    stream = io.BytesIO()
    picture.save(stream, format="PNG")
    pdf = fitz.open()
    page = pdf.new_page(width=620, height=780)
    page.insert_text((35, 38), "How to draw a character with simple shapes.", fontsize=13)
    page.insert_image(fitz.Rect(20, 80, 600, 700), stream=stream.getvalue())
    blob = pdf.tobytes()
    pdf.close()
    assert len(blob) > 1024 * 1024
    return blob


def test_chunk_upload_larger_than_proxy_default(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "DATA_DIR", tmp_path)
    monkeypatch.setattr(webapp, "ArgosTranslator", TranslatorStub)
    monkeypatch.setattr(webapp, "MAX_SESSIONS", 20)
    original = make_large_pdf()
    with TestClient(webapp.app) as client:
        init = client.post("/api/uploads", json={
            "filename": "Manual de Personagens.pdf", "size": len(original)
        })
        assert init.status_code == 200, init.text
        info = init.json()
        uid = info["upload_id"]
        headers = {"X-Upload-Token": info["token"]}
        assert info["chunk_size"] == 262144
        assert info["chunks"] >= 5

        # Cada chamada é 256 KiB, em vez de mandar 1MB+ de uma vez.
        chunks = [original[p:p+info["chunk_size"]]
                  for p in range(0, len(original), info["chunk_size"])]
        for index, chunk in enumerate(chunks):
            reply = client.post(
                f"/api/uploads/{uid}/chunks/{index}",
                content=chunk, headers=headers
            )
            assert reply.status_code == 200, reply.text
        assert client.post(f"/api/uploads/{uid}/complete",headers=headers).status_code == 200
        with fitz.open(stream=original, filetype="pdf") as doc:
            original_hashes = image_fingerprints(doc)
        request = client.post(
            f"/api/uploads/{uid}/translate", headers=headers,
            json={"layout": "conservador", "source": "Inglês", "backend": "argos",
                  "ocr": "nunca"}
        )
        assert request.status_code == 200, request.text
        state = None
        for _ in range(100):
            state = client.get(f"/api/uploads/{uid}/status", headers=headers).json()
            if state["phase"] in {"concluido", "erro"}:
                break
            time.sleep(0.1)
        assert state["phase"] == "concluido", state
        result = client.get(
            f"/api/uploads/{uid}/download?token={info['token']}")
        assert result.status_code == 200, result.text
        assert result.headers["content-type"].startswith("application/pdf")
        with fitz.open(stream=result.content, filetype="pdf") as doc:
            assert len(doc) == 2
            assert image_fingerprints(doc)[0] == original_hashes[0]
            assert "traduzido" in doc[1].get_text().lower()


def test_prevent_oversized_chunk_and_unknown_session(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "DATA_DIR", tmp_path)
    with TestClient(webapp.app) as client:
        init = client.post("/api/uploads",json={"filename":"test.pdf","size":2})
        assert init.status_code == 200
        values = init.json()
        path = f"/api/uploads/{values['upload_id']}/chunks/0"
        assert client.post(path,content=b"%PDF-",
                           headers={"X-Upload-Token":values["token"]}).status_code == 400
        assert client.post(path,content=b"X"*(262144+1),
                           headers={"X-Upload-Token":values["token"]}).status_code == 413
        assert client.post(path,content=b"AB",
                           headers={"X-Upload-Token":"token-errado"}).status_code == 404
        assert client.get("/health").status_code == 200
        assert "Upload em partes" in client.get("/").text
