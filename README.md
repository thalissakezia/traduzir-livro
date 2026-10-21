# Traduzir Livro 📚

Upload de um PDF ilustrado → tradução para português brasileiro → download de PDF com ilustrações preservadas.

Interface gratuita em português com Gradio, PyMuPDF, Tesseract OCR, ReportLab e Argos Translate. IA local Ollama opcional.

**Modo mais seguro:** mantém cada página original e insere em seguida outra página com sua tradução. **Modo substituição:** tenta trocar somente texto nativo sem mexer nos objetos de imagem; em páginas escaneadas retorna ao modo seguro.

### Rodar com Docker

```bash
docker build -t traduzir-livro .
docker run --rm -p 7860:7860 traduzir-livro
```

Abra http://localhost:7860

### Rodar com Python 3.11

Instale Tesseract (idioma inglês) e fonte DejaVu Sans; depois execute:

```bash
pip install -r requirements.txt
python app.py
```

O Argos baixa o modelo de idiomas na primeira execução e pode funcionar offline depois disso. Para fluência superior, instale Ollama no mesmo servidor e baixe qwen2.5:7b.

### Limitações

Traduções automáticas e OCR precisam de revisão. Processamento de 300+ páginas exige recursos de CPU, RAM e tempo. A Vercel é ótima para a interface, mas inadequada para executar OCR e inferência de livros extensos diretamente em funções serverless. Deploy recomendado: Docker num servidor apropriado ou Hugging Face Space Docker com recursos suficientes. Arquivos PDF não devem ser colocados no GitHub.

As imagens raster são comparadas por SHA-256 dos fluxos originais; o modo conservador não modifica gráficos vetoriais nem imagens. No modo substituição, fundos com textos complexos podem mudar visualmente.

Implementação independente inspirada em ideias de [pdf-layout-translate](https://github.com/joanmarcriera/pdf-layout-translate) e [jctots/pdf-translate](https://github.com/jctots/pdf-translate), ambos MIT. Nenhum código AGPL foi incorporado. Respeite os direitos autorais dos livros; traduções não devem ser distribuídas sem autorização.

### Testes

```bash
pip install pytest
python -m pytest -q
```
