"""Tradução de PDFs ilustrados, priorizando fidelidade das imagens."""
from __future__ import annotations
import hashlib
import io
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from xml.sax.saxutils import escape
import fitz

SOURCE_LANGUAGES = {"Inglês": "en", "Espanhol": "es", "Francês": "fr", "Alemão": "de", "Italiano": "it"}
MAX_PAGES = 850
MAX_FILE_BYTES = 160 * 1024 * 1024


@dataclass
class Paragraph:
    text: str
    rect: tuple[float, float, float, float] | None
    fontsize: float = 11.0
    translated: str = ""
    source: str = "native"


@dataclass
class Result:
    output_pdf: str
    pages_original: int
    pages_final: int
    pages_ocr: int
    pages_companion: int
    image_verified: bool
    messages: list[str]


class ArgosTranslator:
    """Tradutor livre, executado localmente após baixar o modelo."""
    def __init__(self, source: str, target: str = "pt"):
        try:
            from argostranslate import package, translate
        except ImportError as exc:
            raise RuntimeError("Argos Translate não está instalado.") from exc
        installed = translate.get_installed_languages()
        src = next((l for l in installed if l.code == source), None)
        tgt = next((l for l in installed if l.code == target), None)
        direct = self._get(src, tgt)
        if direct is None:
            try:
                package.update_package_index()
                match = next((p for p in package.get_available_packages()
                              if p.from_code == source and p.to_code == target), None)
                if not match:
                    raise RuntimeError(f"Sem modelo gratuito de {source} para {target}.")
                package.install_from_path(match.download())
                installed = translate.get_installed_languages()
                src = next((l for l in installed if l.code == source), None)
                tgt = next((l for l in installed if l.code == target), None)
                direct = self._get(src, tgt)
            except Exception as exc:
                raise RuntimeError("Falha ao instalar modelo de tradução. "
                                   "É preciso internet na primeira execução.") from exc
        if direct is None:
            raise RuntimeError("Modelo Argos indisponível.")
        self.model = direct

    @staticmethod
    def _get(src, tgt):
        if src is None or tgt is None:
            return None
        try:
            return src.get_translation(tgt)
        except Exception:
            return None

    def translate(self, text: str) -> str:
        return self.model.translate(text)


class OllamaTranslator:
    """IA local opcional: não usa API paga nem permite destinos arbitrários."""
    def __init__(self, model: str = "qwen2.5:7b"):
        self.model = re.sub(r"[^\w.:-]", "", model) or "qwen2.5:7b"

    def translate(self, text: str) -> str:
        import requests
        prompt = (
            "Traduza para português brasileiro natural, editorial, como um manual "
            "de ilustração profissional publicado no Brasil. Não resuma, não explique, "
            "não elimine informações, não adicione comentários. Preserve nomes, números "
            "e nomes próprios. Glossário: character design=design de personagens; "
            "gesture drawing=desenho gestual; line of action=linha de ação; "
            "squash and stretch=achatar e esticar; model sheet=folha-modelo; "
            "appeal=atratividade visual. Retorne SOMENTE a tradução.\n\n" + text
        )
        try:
            response = requests.post("http://127.0.0.1:11434/api/generate", json={
                "model": self.model, "prompt": prompt, "stream": False,
                "options": {"temperature": 0.12, "num_ctx": 8192},
            }, timeout=280)
            response.raise_for_status()
            result = response.json().get("response", "").strip()
            if not result:
                raise RuntimeError("Modelo local devolveu tradução vazia.")
            return result
        except requests.RequestException as exc:
            raise RuntimeError("Ollama não está no mesmo servidor. "
                               "Inicie o Ollama e baixe o modelo escolhido.") from exc


def image_fingerprints(doc: fitz.Document) -> list[tuple[str, ...]]:
    """SHA-256 do stream raster codificado, por imagem de cada página."""
    result = []
    for page in doc:
        result.append(tuple(sorted(
            hashlib.sha256(doc.xref_stream_raw(info[0])).hexdigest()
            for info in page.get_images(full=True)
        )))
    return result


def extract_native(page: fitz.Page) -> list[Paragraph]:
    result = []
    for block in page.get_text("dict", sort=True).get("blocks", []):
        if block.get("type") != 0:
            continue
        lines, sizes = [], []
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            if text.strip():
                lines.append(text.strip())
                sizes += [float(span.get("size", 11)) for span in line.get("spans", [])]
        body = " ".join(lines).strip()
        if body and re.search(r"\w", body):
            fontsize = max(7, min(28, (sum(sizes) / len(sizes)) if sizes else 11))
            result.append(Paragraph(body, tuple(float(x) for x in block["bbox"]), fontsize))
    return result


def extract_ocr(page: fitz.Page, lang: str = "eng") -> list[Paragraph]:
    import pytesseract
    from pytesseract import Output
    from PIL import Image
    scale = 2.2
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    try:
        data = pytesseract.image_to_data(
            image, lang=lang, output_type=Output.DICT, config="--psm 3"
        )
    except pytesseract.TesseractError as exc:
        raise RuntimeError(f"OCR indisponível no idioma {lang}.") from exc
    groups = {}
    for i, token in enumerate(data["text"]):
        try:
            confidence = float(data["conf"][i])
        except (TypeError, ValueError):
            continue
        if not token.strip() or confidence < 33:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        left, top = data["left"][i] / scale, data["top"][i] / scale
        right = left + data["width"][i] / scale
        bottom = top + data["height"][i] / scale
        groups.setdefault(key, []).append((token.strip(), left, top, right, bottom))
    return [
        Paragraph(
            " ".join(v[0] for v in values),
            (min(v[1] for v in values), min(v[2] for v in values),
             max(v[3] for v in values), max(v[4] for v in values)),
            10, source="ocr"
        )
        for values in groups.values()
        if len(" ".join(v[0] for v in values).strip()) > 1
    ]


def translate_paragraphs(paragraphs, translator, cache):
    for paragraph in paragraphs:
        if paragraph.text in cache:
            paragraph.translated = cache[paragraph.text]
            continue
        if not re.search(r"[a-zA-ZÀ-ÿ]", paragraph.text):
            paragraph.translated = paragraph.text
        else:
            sentences = re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ú])", paragraph.text)
            batches, buffer = [], ""
            for sentence in sentences:
                if buffer and len(buffer) + len(sentence) > 1200:
                    batches.append(buffer)
                    buffer = ""
                buffer += (" " if buffer else "") + sentence
            if buffer:
                batches.append(buffer)
            paragraph.translated = " ".join(translator.translate(s).strip() for s in batches)
            if not paragraph.translated:
                raise RuntimeError("Tradução vazia; arquivo não será gerado.")
        cache[paragraph.text] = paragraph.translated


def _get_font() -> str | None:
    possibilities = [
        os.environ.get("PDF_FONT_PATH", ""),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    return next((p for p in possibilities if p and Path(p).is_file()), None)


def _companion_pdf(paragraphs, original_number, page_size) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph as RLParagraph, Spacer
    width, height = max(350, page_size[0]), max(470, page_size[1])
    font, face = _get_font(), "Helvetica"
    if font:
        pdfmetrics.registerFont(TTFont("ImageSafePT", font))
        face = "ImageSafePT"
    normal = ParagraphStyle(
        "main", fontName=face, fontSize=10.5, leading=15, spaceAfter=12,
        textColor=colors.HexColor("#202b3c")
    )
    heading = ParagraphStyle(
        "head", parent=normal, fontSize=15, leading=20, spaceAfter=19,
        textColor=colors.HexColor("#36577d")
    )
    tiny = ParagraphStyle(
        "tiny", parent=normal, fontSize=8, leading=11,
        textColor=colors.HexColor("#737e8a")
    )
    stream = io.BytesIO()
    doc = SimpleDocTemplate(
        stream, pagesize=(width, height), leftMargin=32, rightMargin=32,
        topMargin=35, bottomMargin=32, title=f"Tradução da página {original_number}"
    )
    content = [
        RLParagraph(f"Tradução • página original {original_number}", heading),
        RLParagraph("Ilustrações originais intactas na página anterior.", tiny),
        Spacer(1, 14)
    ]
    if not paragraphs:
        content.append(RLParagraph("Nenhum texto legível identificado nesta página.", normal))
    for p in paragraphs:
        content.append(RLParagraph(
            escape(p.translated or p.text).replace("\n", "<br/>"), normal
        ))
    doc.build(content)
    return stream.getvalue()


def _fit_native(page, paragraphs, font_path):
    """Remove somente texto digital; não altera imagens ou gráficos vetoriais."""
    if not paragraphs:
        return True
    for p in paragraphs:
        if p.rect is None:
            return False
        box = fitz.Rect(p.rect)
        if box.width < 24 or box.height < 7:
            return False
        if len(p.translated) > max(1, len(p.text)) * 2.9 and box.height < p.fontsize * 2.2:
            return False
    try:
        page.insert_font(fontname="ImageSafe", fontfile=font_path)
        for p in paragraphs:
            page.add_redact_annot(fitz.Rect(p.rect), fill=False, cross_out=False)
        page.apply_redactions(images=0, graphics=0, text=0)
        for p in paragraphs:
            r = fitz.Rect(p.rect)
            r = fitz.Rect(
                max(0, r.x0 - 1), max(0, r.y0 - 2),
                min(page.rect.width, r.x1 + 3), min(page.rect.height, r.y1 + 3)
            )
            fitted = False
            for size in [min(20, p.fontsize), min(18, p.fontsize * .9),
                         min(16, p.fontsize * .8), min(14, p.fontsize * .7), 6.2]:
                shape = page.new_shape()
                if shape.insert_textbox(
                    r, p.translated, fontname="ImageSafe", fontfile=font_path, fontsize=max(6.2, size),
                    lineheight=1.0
                ) >= 0:
                    shape.commit(overlay=True)
                    fitted = True
                    break
            if not fitted:
                return False
    except Exception:
        return False
    return True


def process_pdf(
    input_path: str,
    output_path: str,
    translator,
    source_lang: str = "en",
    layout: str = "conservador",
    ocr_policy: str = "automatico",
    progress: Callable[[int, int, str], None] | None = None,
) -> Result:
    path = Path(input_path)
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Envie um PDF com até 160 MB.")
    with fitz.open(input_path) as source:
        if source.needs_pass:
            raise ValueError("PDF protegido por senha. Desbloqueie-o primeiro.")
        n = len(source)
        if n == 0 or n > MAX_PAGES:
            raise ValueError("Permitidos de 1 a 850 páginas.")
        image_hashes = image_fingerprints(source)
        extracted, pages_ocr, cache = [], 0, {}
        ocr_lang = {"en": "eng", "es": "spa", "fr": "fra", "de": "deu", "it": "ita"}.get(source_lang, "eng")
        for i, page in enumerate(source):
            if progress:
                progress(i + 1, n, "Lendo e traduzindo")
            native = extract_native(page)
            native_size = sum(len(p.text) for p in native)
            should_ocr = (ocr_policy == "sempre" or
                          (ocr_policy == "automatico" and native_size < 40))
            if should_ocr:
                ocr_text = extract_ocr(page, ocr_lang)
                if ocr_text:
                    extracted.append((ocr_text, "ocr"))
                    pages_ocr += 1
                else:
                    extracted.append((native, "native"))
            else:
                extracted.append((native, "native"))
            translate_paragraphs(extracted[-1][0], translator, cache)
        if progress:
            progress(n, n, "Montando e verificando o PDF")

    output = fitz.open(input_path)
    counts, warnings = [0] * n, []
    font = _get_font()
    try:
        for i in reversed(range(n)):
            texts, kind = extracted[i]
            safe_to_replace = (layout == "substituir" and kind == "native"
                               and bool(font) and bool(texts))
            if safe_to_replace:
                testdoc = fitz.open()
                testdoc.insert_pdf(output, from_page=i, to_page=i)
                success = _fit_native(testdoc[0], texts, font)
                if success and image_fingerprints(testdoc)[0] == image_hashes[i]:
                    output.delete_page(i)
                    output.insert_pdf(testdoc, start_at=i)
                    testdoc.close()
                    continue
                testdoc.close()
                warnings.append(f"Página {i+1}: tradução em folha adicional para preservar o desenho.")
            note = fitz.open(
                stream=_companion_pdf(texts, i+1, (output[i].rect.width, output[i].rect.height)),
                filetype="pdf"
            )
            counts[i] = len(note)
            output.insert_pdf(note, start_at=i + 1)
            note.close()

        index = 0
        for i in range(n):
            hash_now = tuple(sorted(
                hashlib.sha256(output.xref_stream_raw(info[0])).hexdigest()
                for info in output[index].get_images(full=True)
            ))
            if hash_now != image_hashes[i]:
                raise RuntimeError(f"Falha na verificação das imagens da página {i+1}.")
            index += 1 + counts[i]

        # A compressão automática modificaria os bytes codificados de imagens!
        output.save(output_path, garbage=0, deflate=False)
        return Result(output_path, n, len(output), pages_ocr, sum(counts), True, warnings)
    finally:
        output.close()
