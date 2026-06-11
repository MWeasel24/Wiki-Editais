# WikiEditais

**WikiEditais** é um protótipo de IA vertical para análise de editais públicos de concursos. A proposta é transformar PDFs de editais em uma base de conhecimento navegável e consultável, usando o modelo Wiki baseado em LLM com RAG.

## 1. Problema

Editais de concursos públicos costumam ser longos, pouco amigáveis e cheios de tabelas, anexos, datas, cargos, requisitos e regras específicas. Isso dificulta a consulta rápida por candidatos e também a comparação entre editais.

O WikiEditais busca resolver esse problema criando uma interface que permite:

- enviar um edital em PDF;
- extrair texto, tabelas e metadados;
- organizar cargos, cronograma, inscrições, conteúdo e fontes;
- gerar uma wiki temática do edital;
- consultar o edital por chat com apoio de RAG;
- revisar manualmente informações incertas;
- avaliar a qualidade da wiki e do chat.

## 2. Arquitetura da solução

Fluxo principal:

```text
PDF do edital
↓
Extração de texto e tabelas
↓
Limpeza, metadados e chunking
↓
Extração estruturada: cargos, cronograma, inscrição, taxa, prova etc.
↓
Geração da wiki em Markdown
↓
Mapa do edital / base temática
↓
Indexação RAG com embeddings + ChromaDB
↓
Consulta por chat usando wiki, dados estruturados e trechos recuperados
```

Componentes principais:

- **Ingestão:** carrega PDFs e extrai texto/tabelas.
- **Pré-processamento:** limpa ruído, separa chunks e preserva fontes.
- **Wiki:** gera páginas por tema, como resumo, cargos, cronograma, conteúdo, fontes e mapa do edital.
- **RAG:** usa embeddings e ChromaDB para recuperar trechos relevantes.
- **LLM:** gera sínteses, páginas e respostas baseadas no contexto recuperado.
- **Revisão:** permite ajuste humano de campos e dados extraídos.
- **Análise:** lê JSONs de avaliação e calcula métricas automaticamente.

## 3. Tecnologias utilizadas

- **Python 3.12.10**
- **Flask + HTML/CSS/JS**
- **PyMuPDF** para leitura de PDFs
- **Markdown / markdown2** para renderização da wiki
- **ChromaDB** como banco vetorial
- **Ollama** para execução local dos modelos
- **Qwen 2.5 7B Instruct** como LLM padrão
- **qwen3-embedding:0.6b** como modelo de embeddings
- **JSON/Markdown** para armazenamento local dos dados gerados

## 4. Instalação

Crie e ative um ambiente virtual:

```bash
python -m venv .venv
.venv\Scripts\activate
```

Instale as dependências: (Observação: Necessário Microsoft C++ Build Tools para usar ChromaDB)

```bash
pip install -r requirements.txt
```

Instale os modelos no Ollama:

```bash
ollama pull qwen2.5:7b-instruct
ollama pull qwen3-embedding:0.6b
```

## 5. Execução

Execute a aplicação:

```bash
python app.py
```

Acesse no navegador:

```text
http://127.0.0.1:5000
```

## 6. Exemplos de uso

1. Acessar a área **Debug**.
2. Enviar um PDF de edital.
3. Acompanhar a barra de progresso da ingestão.
4. Abrir o edital processado.
5. Consultar as abas:
   - Resumo;
   - Cargos;
   - Cronograma;
   - Conteúdo;
   - Mapa do edital;
   - Chat.
6. Fazer perguntas como:
   - “Qual é o período de inscrição?”
   - “Quais cargos exigem ensino médio?”
   - “Qual é a taxa de inscrição?”
   - “O que cai na prova objetiva?”
   - “Quando será a prova?”
7. Abrir a aba **Análise** para visualizar as métricas dos JSONs avaliados.

## 7. Decisões técnicas

### Por que LLM Wiki com RAG?

O projeto foi pensado como uma IA vertical para editais públicos. A ideia não é só criar um chatbot de PDF, mas estruturar o edital em uma base de conhecimento navegável, com páginas temáticas e consulta por pergunta. No chat, o RAG entra pra recuperar só o trecho relevante do edital e gerar a resposta com base nele.

### Por que Flask + HTML?

Foi escolhido por ser simples, leve e suficiente para demonstrar o funcionamento do sistema.

### Por que Qwen?

A família Qwen foi escolhida porque é boa para seguir instruções, tem suporte multilíngue e lida bem com contexto longo, o que combina com editais públicos em português.

### Por que modelos quantizados?

Modelos maiores em versão completa ficaram pesados para o hardware usado. Por isso, modelos quantizados foram considerados para permitir testes locais com modelos maiores, reduzindo uso de memória e mantendo qualidade aceitável.

### Por que não usar modelos cloud?

Modelos cloud foram considerados, mas ficaram inviáveis para o projeto por limite de tokens em editais grandes, custo de uso recorrente e dependência externa.

## 8. Comparação de modelos

Hardware de referência:

```text
GPU: RTX 2060 Super 8GB VRAM
RAM: 16GB
CPU: Intel i5-12400F
```

| Modelo Qwen | Tempo wiki | Tempo RAG | Total médio por edital | Qualidade da wiki |
|---|---:|---:|---:|---:|
| qwen2.5:0.5b-instruct | ~25s | ~50s | ~1–2 min | 38% |
| qwen2.5:1.5b-instruct | ~40s | ~1min20s | ~2–3 min | 48% |
| qwen2.5:3b-instruct | ~1 min | ~2 min | ~3–4 min | 62% |
| qwen2.5:7b-instruct | ~2 min | ~3 min | ~5–6 min | 85% |
| qwen2.5:14b-instruct quantizado | ~5 min | ~7 min | ~12–14 min | 91% |
| qwen2.5:32b-instruct quantizado | 20 min+ | 30 min+ | 50 min+ | 94% |

O modelo adotado como padrão foi o **qwen2.5:7b-instruct**, pois apresentou o melhor equilíbrio entre qualidade, tempo e viabilidade local. O 14B quantizado gerou resultados melhores, mas ficou mais pesado para uso contínuo.

## 9. Resultados da avaliação

A avaliação foi feita com JSONs manuais, usando notas de 0 a 1 para itens de Wiki e Chat. O sistema calcula automaticamente as métricas.

Métricas principais:

| Métrica | Resultado |
|---|---:|
| Arquivos avaliados | 2 |
| Itens avaliados | 80 |
| Geral | 83,9% |
| Wiki | 86,9% |
| Chat | 80,9% |
| Com fonte | 100,0% |
| Média 0–1 | 0,839 |

Por tipo:

| Tipo | Total | Média |
|---|---:|---:|
| Wiki | 40 | 86,9% |
| Chat | 40 | 80,9% |

O que significa cada métrica:

- Geral: É a média de todas as notas dos JSONs, juntando Wiki e Chat. É uma nota média manual de qualidade, de 0 a 1, convertida para porcentagem.
- Wiki: Média só dos itens tipo: "wiki". Mede se a wiki ficou útil, organizada, navegável e fiel ao edital.
- Chat: Média só dos itens tipo: "chat". Mede se o chat respondeu bem perguntas reais que um usuário faria.
- Com fonte: Percentual de itens em que fonte_ok: true. Mede se a resposta/resultado tinha fonte, contexto ou era conferível no edital.
- Acertos / Parciais / Erros: Classificação automática a partir da nota:

```
nota >= 0.85 → acertou
0.5 <= nota < 0.85 → parcial
nota < 0.5 → errou
```

## 10. Limitações conhecidas

- O sistema foi pensado especificamente para **editais de concursos públicos**.
- Pode não funcionar bem para outros tipos de edital ou documentos jurídicos sem adaptação.
- Não é uma LLM Wiki pura e totalmente autônoma; é uma solução híbrida com extração, estruturação, wiki temática e RAG.
- Por usar modelos open-source pequenos/médios, algumas etapas exigem regras auxiliares, validação e revisão humana.
- Conteúdo programático pode variar muito entre editais e ainda é uma das partes mais difíceis.
- PDFs com tabelas muito quebradas podem gerar cargos, requisitos ou datas incompletas.
- O chat evita inventar respostas, mas pode responder de forma incompleta quando a recuperação não encontra bons trechos.
