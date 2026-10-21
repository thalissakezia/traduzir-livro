import io
import fitz
from PIL import Image, ImageDraw
from engine import image_fingerprints, process_pdf

class FakeTranslator:
    def translate(self, text):
        return "Tradução: " + text

def sample(tmp_path, scanned=False):
    image = Image.new("RGB", (150, 110), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((14, 15, 130, 100), fill="#d08779", outline="#332c3c", width=4)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    doc = fitz.open()
    page = doc.new_page(width=480, height=580)
    page.insert_image(fitz.Rect(40, 95, 350, 325), stream=buffer.getvalue())
    if not scanned:
        page.insert_text((30, 65), "Character design is fun", fontsize=12)
    file = tmp_path / "source.pdf"
    doc.save(str(file))
    doc.close()
    return file

def test_conservative_preserves_images(tmp_path):
    source = sample(tmp_path)
    target = tmp_path / "result.pdf"
    result = process_pdf(str(source), str(target), FakeTranslator(), ocr_policy="nunca")
    with fitz.open(str(source)) as old, fitz.open(str(target)) as new:
        assert result.image_verified
        assert len(new) == 2
        assert image_fingerprints(old)[0] == image_fingerprints(new)[0]
        assert "Tradução" in new[1].get_text()

def test_replacement_preserves_images(tmp_path):
    source = sample(tmp_path)
    target = tmp_path / "result.pdf"
    result = process_pdf(str(source), str(target), FakeTranslator(),
                         layout="substituir", ocr_policy="nunca")
    with fitz.open(str(source)) as old, fitz.open(str(target)) as new:
        assert result.image_verified
        assert image_fingerprints(old)[0] == image_fingerprints(new)[0]
        assert "Tradução" in " ".join(p.get_text() for p in new)

def test_scanned_is_not_redacted(tmp_path):
    source = sample(tmp_path, scanned=True)
    target = tmp_path / "result.pdf"
    result = process_pdf(str(source), str(target), FakeTranslator(),
                         layout="substituir", ocr_policy="nunca")
    with fitz.open(str(source)) as old, fitz.open(str(target)) as new:
        assert result.image_verified
        assert len(new) == 2
        assert image_fingerprints(old)[0] == image_fingerprints(new)[0]

def test_five_pages_have_matching_translations(tmp_path):
    source = sample(tmp_path)
    doc = fitz.open(str(source))
    for i in range(4):
        doc.new_page().insert_text((25, 50), f"English manual page number {i+2}")
    doc.saveIncr()
    doc.close()
    target = tmp_path / "result.pdf"
    result = process_pdf(str(source), str(target), FakeTranslator(), ocr_policy="nunca")
    with fitz.open(str(target)) as new:
        assert result.pages_original == 5
        assert len(new) == 10
        for i in range(5):
            assert "Tradução" in new[2*i+1].get_text()


def test_large_310_page_book_keeps_every_illustration(tmp_path):
    """310 illustrated source pages become 620 pages without image re-encoding."""
    import fitz
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "#945da3").save(buf, format="PNG")
    doc = fitz.open()
    for i in range(310):
        page = doc.new_page(width=400, height=520)
        page.insert_image(fitz.Rect(35, 110, 370, 450), stream=buf.getvalue())
        page.insert_text((30, 45), f"Character design lesson {i + 1}")
    src = tmp_path / "original-310.pdf"
    doc.save(str(src))
    doc.close()
    final = tmp_path / "translated-310.pdf"
    result = process_pdf(str(src), str(final), FakeTranslator(), ocr_policy="nunca")
    assert result.pages_original == 310
    assert result.pages_final == 620
    assert result.image_verified
    with fitz.open(str(src)) as original, fitz.open(str(final)) as translated:
        original_images = image_fingerprints(original)
        translated_images = image_fingerprints(translated)
        assert all(original_images[i] == translated_images[i * 2] for i in range(310))
