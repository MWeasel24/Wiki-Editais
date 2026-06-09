# WikiEditais — LLM Wiki de Editais Públicos

> Versão final corrigida: **v20 Microcopy + Template Wiki Renderer**. Esta versão corrige o ponto que fazia modelos 7B/8B colapsarem: o Python estrutura e monta as páginas; a LLM escreve apenas microtextos curtos, com prompts pequenos, para dar leitura editorial sem virar dump de PDF.

WikiEditais é um micro SaaS acadêmico para transformar PDFs de editais de concursos públicos em uma **LLM Wiki** navegável, editável e consultável. A proposta é criar uma base de conhecimento por edital, com páginas Markdown organizadas por tema, card público para o site e chat sobre a wiki.

## Objetivo

O objetivo não é criar um chatbot genérico de PDF nem um extrator perfeito de campos. O objetivo é:

1. ingerir um edital em PDF/TXT/MD;
2. recuperar trechos relevantes por tópico;
3. extrair fatos determinísticos e, quando disponível, complementar com JSON pequeno por tópico;
4. montar páginas de wiki por templates editoriais;
5. usar a LLM como microeditora para introduções e orientações curtas;
6. gerar um card público seguro para o site;
7. permitir consulta e edição da base.

## Arquitetura final

```text
PDF/TXT/MD
↓
pages.json
↓
chunks.json + section_hits.json
↓
sections.json
↓
deterministic_facts.json + llm_topic_facts.json curto
↓
topic_facts.json
↓
Python template renderer + LLM microcopy
↓
wiki/*.md
↓
schema.json / public_schema.json
↓
site + chat
```

## Estratégia de LLM Wiki

A versão final usa um motor chamado **Microcopy Template Wiki Engine**:

- o PDF é fonte bruta, não verdade direta;
- cada tópico tem contrato editorial próprio;
- a LLM não recebe mais prompts gigantes para escrever páginas inteiras;
- a extração determinística monta fatos estruturados;
- a LLM recebe JSON pequeno e escreve apenas introdução/interpretação curta;
- o Python monta a página completa com seções, tabelas e fontes;
- fallback existe, mas é marcado como modo degradado;
- score alto só acontece quando há LLM ativa e páginas úteis.

## Páginas geradas

- `MASTER.md`: visão geral do edital;
- `dados-principais.md`: órgão, banca, status e dados centrais;
- `inscricoes.md`: período, taxa, pagamento e isenção;
- `cargos-e-vagas.md`: cargos, vagas, requisitos, carga horária e salário;
- `cronograma.md`: eventos e prazos;
- `provas-e-etapas.md`: prova objetiva/prática, regras e pontuação;
- `conteudo-programatico.md`: guia de estudos;
- `requisitos.md`: posse, investidura e documentos;
- `recursos.md`: regras de recurso;
- `retificacoes.md`: erratas, suspensão e prorrogação;
- `fontes.md`: auditoria das páginas usadas.

## Tecnologias

- Python;
- Flask + HTML/CSS;
- PyMuPDF para extração de texto por página;
- Ollama/Groq para LLM;
- Markdown como base de conhecimento;
- JSON para artefatos estruturados.

## Modelos configurados

| Modelo | Provedor | Uso | Tempo médio de indexação* | Performance no projeto* | Motivo de inclusão |
|---|---|---|---:|---:|---|
| Llama 3.2 3B Local | Ollama | chat/index/compare | 4–8 min | 62% | Leve e roda em máquinas simples, mas tem menor qualidade editorial. |
| Qwen 2.5 7B Local | Ollama | chat/index/compare | 7–14 min | 76% | Melhor equilíbrio entre português, custo local e qualidade. **Modelo padrão.** |
| Qwen 2.5 14B Local | Ollama | index/chat/compare | 14–28 min | 81% | Melhor escrita e leitura de instruções, mas mais pesado. |
| Groq Llama 3.3 70B | Groq | index/compare/chat | 2–5 min | 84% | Ótima qualidade, mas depende de API e limite externo. |
| Groq Llama 3.1 8B Instant | Groq | chat/compare/index | 1–3 min | 72% | Muito rápido para chat e testes. |
| Mistral 7B Local | Ollama | chat/index/compare | 7–13 min | 70% | Alternativa local rápida, mas menos estável em JSON longo. |
| Gemma 2 9B Local | Ollama | chat/index/compare | 9–18 min | 73% | Boa fluência, mas desempenho irregular em editais longos. |

\*Métricas acadêmicas estimadas para o projeto, considerando o edital de Parintins-AM e execução local/API opcional. O desempenho ficou relativamente próximo entre modelos porque o maior gargalo foi a qualidade do PDF e a estrutura do edital, não apenas o tamanho do modelo.

## Por que Qwen 2.5 7B como padrão?

Foi escolhido como padrão porque oferece boa capacidade em português, segue instruções JSON melhor que modelos menores e ainda pode rodar localmente em hardware intermediário. O Qwen 14B e o Groq 70B tiveram resultados melhores, mas com custo computacional/API maior.

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Opcional, para qualidade real de LLM Wiki:

```bash
ollama pull qwen2.5:7b
```

## Execução

```bash
python main.py
```

Acesse:

```text
http://127.0.0.1:5000
```

## Como usar

1. Abra `/debug`.
2. Envie um PDF de edital.
3. Escolha o modelo de indexação.
4. Aguarde a geração da wiki.
5. Acesse o edital na home.
6. Navegue pelas páginas Markdown.
7. Use o chat para perguntar sobre o edital.
8. Edite a wiki/schema se necessário.

## Avaliação manual — edital de Parintins-AM

O edital usado como teste possui suspensão, prorrogação, erratas, anexo de cargos, regras de inscrição, prova objetiva, recursos e conteúdo programático. Isso tornou o documento difícil e adequado para avaliar a proposta.

Resultados esperados com LLM ativa:

| Área | Resultado esperado |
|---|---:|
| Wiki editorial | 65–78% |
| Chat sobre páginas | 75–85% |
| Card público/site | 65–80% |
| Workflow automático completo | 55–70% |

A pontuação da wiki não é máxima porque editais longos com erratas e tabelas quebradas ainda exigem revisão humana.

## Conjunto de 20 perguntas manuais

### Perguntas fáceis

1. Qual é o órgão responsável pelo edital?
2. Qual é a cidade/UF do concurso?
3. Qual é a banca ou instituição organizadora?
4. O concurso está suspenso?
5. Até quando as inscrições foram prorrogadas?
6. Qual é o site citado para publicações/inscrições?
7. Qual é a taxa para nível fundamental?
8. Qual é a taxa para nível médio/técnico?
9. Qual é a taxa para nível superior?
10. Qual é a data prevista da prova objetiva?

### Perguntas difíceis

11. Quais erratas alteraram o quadro de vagas?
12. O que mudou em relação ao cargo Motorista Categoria D?
13. Qual é a diferença entre salário e adicional para professores?
14. Como a suspensão afeta o cronograma original?
15. Quais cargos possuem salários mais altos?
16. Quais cargos exigem registro em conselho profissional?
17. Como funcionam os recursos contra gabarito ou resultado?
18. Quais documentos são exigidos para posse?
19. Como a wiki trata informações em “Onde se lê / Leia-se”?
20. Quais informações devem ser revisadas manualmente antes de publicação final?

Resultado relatado na avaliação manual: **16/20 perguntas respondidas corretamente**, com melhor desempenho nas perguntas diretas e falhas nas perguntas que exigem consolidação de várias erratas.

## Limitações conhecidas

- Sem LLM ativa, a wiki cai em modo degradado e deve ser revisada.
- Tabelas muito longas e quebradas podem exigir correção manual.
- Erratas “Onde se lê / Leia-se” ainda são difíceis de consolidar automaticamente.
- O sistema prioriza não inventar; campos incertos podem ficar vazios.
- O card do site é conservador; a wiki contém mais detalhes.

## Checklist do trabalho

- [x] Domínio definido: concursos públicos.
- [x] Base de conhecimento própria com PDFs de editais.
- [x] Ingestão e pré-processamento por página.
- [x] Estruturação em páginas de wiki.
- [x] Recuperação por tópicos.
- [x] LLM open-source/self-hosted via Ollama.
- [x] Interface web com Flask.
- [x] Chat com base nas páginas Markdown.
- [x] Comparação de modelos.
- [x] Avaliação manual com perguntas fáceis e difíceis.
- [x] Documentação de limitações.
- [x] Demonstração possível em tempo real.

## Observação final

Este projeto é uma **LLM Wiki com recuperação auxiliar**, não um RAG clássico puro. A recuperação serve para encontrar trechos relevantes; o produto final é a wiki escrita e navegável.

## Motor v20: Microcopy + Template Renderer

A principal correção desta versão é que a base de conhecimento não é mais tratada como um simples `source.md`. O sistema passa a gerar artefatos intermediários que representam conhecimento:

| Artefato | Função |
|---|---|
| `pages.json` | texto por página extraído do PDF |
| `chunks.json` | blocos pesquisáveis por tópico |
| `sections.json` | trechos recuperados por página da wiki |
| `evidence_cards.json` | cartões de evidência com fatos auditáveis |
| `topic_facts.json` | fatos estruturados por tema |
| `wiki_plan.json` | plano editorial de cada página |
| `*.md` | páginas finais da LLM Wiki |

A wiki final é montada por templates a partir de fatos estruturados. A LLM não escreve mais páginas inteiras; ela só produz microcopy curta. O `source.md` continua existindo, mas somente como arquivo de auditoria.

### Como uma página deve ser escrita

Cada página segue uma função editorial. Exemplo para `cargos-e-vagas.md`:

1. explicar o que são cargos, vagas, carga horária, salário e requisitos;
2. mostrar resumo das oportunidades;
3. apresentar tabela apenas com cargos reais;
4. avisar quando houver retificação ou tabela incerta;
5. citar fontes.

Isso evita que frases como “o candidato deverá comparecer” ou “Pessoa com Deficiência” sejam tratadas como cargo.

### Fallback

O sistema ainda funciona sem LLM, mas essa saída é considerada modo degradado. Para uma LLM Wiki mais forte, use Ollama ou Groq durante a indexação.

```bash
ollama pull qwen2.5:7b
ollama serve
python main.py
```

### Validação manual usada na entrega

Com o edital de Parintins-AM, a versão v20 consolida informações úteis com templates e microcopy:

- instituição: Prefeitura Municipal de Parintins;
- localidade: Parintins/AM;
- status: suspenso;
- organizadora: IPRO;
- inscrições: 09/03/2016 a 05/05/2016;
- taxa: R$ 30,00 a R$ 150,00;
- prova: 19/06/2016;
- vagas: 2.055;
- salários: R$ 880,00 a R$ 9.200,00;
- cargos estruturados: 153.

Limitação honesta: o sistema ainda não é extrator perfeito de qualquer tabela. A melhoria da v20 é evitar prompts enormes: com LLM ativa, o modelo só escreve blocos curtos; sem LLM, os templates ainda geram uma wiki legível e estruturada.
