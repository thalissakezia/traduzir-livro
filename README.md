# 📚 Traduzir Livro — PDFs ilustrados em português

Aplicação web em português para traduzir PDFs de livros ilustrados, preservando os desenhos e permitindo **enviar o livro em partes pequenas para evitar HTTP 413 (nginx)**.

## Usar no navegador com GitHub Codespaces

1. Acesse [Abrir Codespaces](https://codespaces.new/thalissakezia/traduzir-livro) na branch `main`.
2. Após abrir o ambiente, abra a aba **Portas** e a porta **7860**. Se aparecer a confirmação de segurança do GitHub, verifique que o endereço pertence ao seu Codespace.
3. A interface terá os botões **Selecionar PDF**, **Traduzir meu livro** e, quando concluir, **Baixar PDF traduzido**.

**Se já houver um Codespace aberto com a interface antiga, atualizar somente a página não altera o código dele.** No Terminal, execute:\n\n```bash\ncd /workspaces/traduzir-livro && git pull --ff-only && python .devcontainer/restart.py\n```\n\nO comando atualiza o código, encerra apenas o processo antigo do tradutor e inicia o novo servidor, conferindo a rota `/health`. Se o ambiente antigo não tiver Git, recrie o Codespace a partir da branch `main` (o novo contêiner já inclui Git).

### Como evitamos o 413

O navegador lê o arquivo original e envia fatias de **256 KiB**, uma de cada vez. O backend junta os blocos exatamente como foram enviados, valida o PDF e só depois o traduz. Não comprimimos, redimensionamos nem convertimos as imagens no upload.

O limite configurado é **320 MB e 850 páginas**, sujeito ao espaço e aos recursos do ambiente. Um arquivo grande pode levar bastante tempo para traduzir, dependendo da CPU, do OCR e do serviço de tradução. O aplicativo usa uma fila para evitar trabalhos simultâneos em excesso.

### Preservação do livro

- **Modo padrão — preservação máxima:** reproduz cada página original sem modificar suas ilustrações e insere depois uma página traduzida. Ideal para manuais ilustrados.
- **Modo substituição:** para textos digitais, tenta substituir o texto na página; se não conseguir de modo seguro, usa uma página de tradução adicional.
- O processo valida com **SHA-256** os fluxos de imagens raster, comparando original e resultado.
- Tradução automática e OCR não garantem equivalência editorial perfeita. Desenhos vetoriais também exigem inspeção visual, principalmente em modo substituição.

### Tecnologias

| Componente | Implementação |
|---|---|
| Interface e upload fragmentado | HTML/JavaScript nativo + FastAPI |
| Montagem de PDF sem rasterização | PyMuPDF |
| OCR | Tesseract |
| Tradução gratuita local | Argos Translate |
| Tradução com IA local opcional | Ollama |
| PDF das traduções e fontes | ReportLab |
| Testes | pytest + GitHub Actions |

### Docker (opção para hospedagem ou execução própria)

```bash
docker build -t traduzir-livro .
docker run --rm -p 7860:7860 traduzir-livro
```

Abra http://localhost:7860 no computador que executa o Docker.

### Python 3.11 (execução alternativa)

Instale Tesseract OCR e fontes DejaVu no sistema. Depois:

```bash
pip install -r requirements.txt
python app.py
```

### Testes

```bash
pip install pytest httpx
python -m pytest -q
```

### Privacidade e despesas

- PDFs são guardados **temporariamente** no disco do servidor e disponibilizados apenas com identificadores e tokens de upload difíceis de adivinhar. Os dados de sessões expiradas são eliminados de forma oportunista após cerca de quatro horas, quando chegam novas solicitações. Isso não equivale a armazenamento permanente.
- Não inclua dados confidenciais ao usar a porta pública de um Codespace. O link pode ser acessado por qualquer pessoa, e a instância não possui autenticação de usuários.
- Códigos e bibliotecas podem ser gratuitos, mas Codespaces possui franquias e eventuais custos de computação; verifique seus limites.
- Não distribua traduções de livros protegidos sem autorização de quem detém os direitos.

O projeto é uma implementação própria. Inspirações: [PDFMathTranslate](https://github.com/PDFMathTranslate/PDFMathTranslate-next), [pdf-layout-translate](https://github.com/joanmarcriera/pdf-layout-translate), [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF). Não foram copiadas partes de código AGPL dos projetos referidos.
