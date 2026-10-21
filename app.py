"""Interface para traduzir livros ilustrados sem APIs pagas."""
from __future__ import annotations
import os
import tempfile
from pathlib import Path
import gradio as gr
from engine import ArgosTranslator, OllamaTranslator, SOURCE_LANGUAGES, process_pdf

CSS = """
.gradio-container {max-width:1050px !important;margin:auto!important}
.hero {text-align:center;padding:10px 0 8px}
.hero h1 {font-size:2.3rem;margin-bottom:8px}
.hero p {font-size:1.05rem;color:#64748b}
"""

def run(pdf_file, source, layout, ocr, backend, ollama_model, progress=gr.Progress()):
    if not pdf_file or not Path(pdf_file).is_file():
        return None, "⚠️ Escolha um PDF antes de começar."
    if Path(pdf_file).suffix.lower() != ".pdf":
        return None, "⚠️ O arquivo precisa ser um PDF."
    try:
        progress(0, desc="Preparando tradutor gratuito...")
        translator = (
            ArgosTranslator(SOURCE_LANGUAGES[source])
            if backend == "Gratuito (Argos)"
            else OllamaTranslator(ollama_model)
        )
        destination = Path(tempfile.mkdtemp(prefix="traduzir-livro-")) / (
            Path(pdf_file).stem[:70] + "-traduzido-ptbr.pdf")
        result = process_pdf(
            pdf_file, str(destination), translator,
            source_lang=SOURCE_LANGUAGES[source],
            layout="conservador" if layout.startswith("Preservação") else "substituir",
            ocr_policy={"Automático": "automatico", "Sempre": "sempre",
                        "Desativado": "nunca"}[ocr],
            progress=lambda i, total, phase: progress(
                i / total if phase != "Montando e verificando o PDF" else 0.99,
                desc=f"{phase} • página {i}/{total}"),
        )
        message = (
            f"✅ **Tradução concluída!** {result.pages_original} páginas originais; "
            f"{result.pages_final} páginas no PDF final; "
            f"{result.pages_ocr} páginas com OCR; "
            f"{result.pages_companion} páginas adicionais em português.\n\n"
            "🖼️ **Dados das imagens raster verificados por SHA-256.**"
        )
        if result.messages:
            message += "\n\n**Páginas protegidas com tradução adicional:**\n" + "\n".join(
                result.messages[:7])
            if len(result.messages) > 7:
                message += f"\n...e mais {len(result.messages)-7} páginas."
        return str(destination), message
    except Exception as exc:
        return None, f"❌ **Erro:** {type(exc).__name__}: {exc}"

with gr.Blocks(
    title="Traduzir Livro • Ilustrações intactas", css=CSS,
    theme=gr.themes.Soft(primary_hue="indigo", neutral_hue="slate")
) as demo:
    gr.HTML("""<div class="hero">
      <h1>📚 Traduzir Livro</h1>
      <p>Seu livro em português. Ilustrações preservadas.</p></div>""")
    with gr.Row():
        with gr.Column(scale=6):
            pdf = gr.File(
                label="1. Envie o livro original (PDF)",
                file_types=[".pdf"], type="filepath")
            source = gr.Dropdown(
                choices=list(SOURCE_LANGUAGES), value="Inglês",
                label="2. Idioma original")
            layout = gr.Radio(
                choices=[
                    "Preservação máxima — original + tradução na página seguinte",
                    "Substituir texto — PDF digital (preserva ilustrações)",
                ],
                value="Preservação máxima — original + tradução na página seguinte",
                label="3. Formato do livro traduzido")
            with gr.Accordion("Opções avançadas", open=False):
                ocr = gr.Radio(
                    choices=["Automático", "Sempre", "Desativado"],
                    value="Automático",
                    label="Ler textos dentro das páginas digitalizadas")
                backend = gr.Radio(
                    choices=["Gratuito (Argos)", "IA local (Ollama)"],
                    value="Gratuito (Argos)", label="Motor de tradução")
                ollama_model = gr.Textbox(
                    value="qwen2.5:7b", label="Modelo Ollama",
                    info="Somente se o Ollama estiver no mesmo servidor.")
            button = gr.Button("Traduzir meu livro", variant="primary", size="lg")
        with gr.Column(scale=5):
            gr.Markdown("### 4. Baixe o livro em português")
            output = gr.File(label="Download do PDF traduzido", interactive=False)
            status = gr.Markdown(
                "Faça o upload e clique em **Traduzir meu livro**.")
            gr.Markdown("""### Proteção de ilustrações
- As imagens originais **não são redimensionadas ou reamostradas**.
- O modo de **preservação máxima** mantém todas as páginas originais inteiras.
- O modo de **substituição** só modifica texto digital e usa páginas extras quando não for seguro.
- A verificação compara os dados originais das imagens raster.

**Importante:** PDFs escaneados usam OCR; pode haver erros em letras pequenas. Traduções automáticas precisam de revisão, e livros de centenas de páginas exigem recursos computacionais. Não carregue livros de terceiros sem ter autorização para a finalidade desejada.""")
    button.click(run, inputs=[pdf, source, layout, ocr, backend, ollama_model],
                 outputs=[output, status], concurrency_limit=1)

demo.queue(default_concurrency_limit=1, max_size=8)
if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("PORT", "7860")),
        max_file_size="160mb",
        show_error=False,
    )
