FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=7860
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-spa tesseract-ocr-fra \
    tesseract-ocr-deu tesseract-ocr-ita fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py engine.py ./
RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser
EXPOSE 7860
CMD ["python", "app.py"]
