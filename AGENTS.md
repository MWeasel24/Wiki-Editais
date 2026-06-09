# AGENTS.md — WikiEditais True LLM Wiki Engine

Este arquivo é o manual operacional do agente/editor usado pelo WikiEditais. Ele não é apenas uma lista de regras. Ele define **como a wiki deve pensar e escrever**.

## 1. Propósito do agente

O agente existe para transformar um edital PDF de concurso público em uma **LLM Wiki interpretada**, navegável e útil para candidatos.

O agente **não deve** produzir um depósito de texto extraído. O PDF é fonte de evidência, não é a página final.

Fluxo mental correto:

```text
PDF bruto
→ evidências
→ fatos estruturados
→ plano de página
→ artigo de wiki
→ revisão
→ card público
```

Fluxo proibido:

```text
PDF bruto
→ cola trechos em Markdown
→ chama isso de wiki
```

## 2. Camadas da base de conhecimento

A base de conhecimento possui quatro camadas:

1. **Fonte bruta**: `pages.json`, `chunks.json`, `source.md`.
2. **Evidências**: `evidence_cards.json`, com fatos auditáveis por tópico.
3. **Fatos por tópico**: `topic_facts.json`, `positions.json`, `timeline.json`.
4. **Wiki editorial**: `MASTER.md` e páginas temáticas `.md`.

A base de conhecimento real da LLM Wiki é a combinação de `evidence_cards.json`, `topic_facts.json` e páginas `.md`. O `source.md` é apenas auditoria.

## 3. Ontologia de concurso público

### Cargo

Cargo é a **função ou oportunidade para a qual o candidato concorre**.

Exemplos válidos:

- Gari
- Motorista
- Enfermeiro
- Professor de Matemática
- Assistente Administrativo
- Técnico em Enfermagem

Não são cargos:

- “O candidato deverá comparecer...”
- “Pessoa com deficiência” isolado
- “Nível Médio” sozinho
- “Remuneração” sozinho
- “Lei nº...”
- “Decreto nº...”
- Conteúdo programático
- Regras de inscrição
- Critérios de desempate

Uma linha forte de cargo normalmente possui pelo menos parte destes campos:

```text
nome do cargo + vagas + carga horária + remuneração + requisito
```

### Vaga

Vaga é a quantidade ofertada para o cargo. Pode aparecer como número, cadastro reserva, CR, ampla concorrência ou PcD.

### Requisito

Requisito é condição para concorrer/assumir: escolaridade, curso, CNH, registro profissional, experiência ou formação específica.

### Salário/remuneração

Salário, vencimento ou remuneração é valor pago pelo cargo. Não confundir com:

- taxa de inscrição;
- auxílio;
- adicional;
- nota/pontuação;
- valor de boleto.

### Taxa

Taxa é valor pago para participar do concurso. Deve aparecer em contexto de inscrição, boleto, pagamento ou escolaridade exigida.

### Cronograma

Cronograma contém eventos operacionais do concurso:

- inscrição;
- pagamento;
- isenção;
- prova;
- gabarito;
- recurso;
- resultado;
- homologação;
- convocação.

Não entram como cronograma:

- datas de leis;
- decretos;
- portarias;
- CNPJ;
- CEP;
- assinatura genérica sem evento;
- datas de legislação citada.

### Status do edital

Status é a situação do certame inteiro. Só deve mudar quando houver ato explícito: suspensão, cancelamento, prorrogação, retificação ou homologação.

“Inscrição cancelada” não significa “concurso cancelado”.

## 4. Como cada página deve ser escrita

Toda página deve parecer escrita por uma pessoa que leu o edital e está explicando para outro candidato.

Formato editorial padrão:

```md
# Título da página

## Visão geral
Explicação humana do tema.

## Informações principais
Dados estruturados, tabelas ou síntese.

## Como interpretar
O que esses dados significam para o candidato.

## Pontos de atenção
Riscos, incertezas, retificações ou necessidade de conferência.

## Fontes usadas
p. X, p. Y
```

A página não deve dizer “trechos recuperados”, “material bruto”, “texto extraído” ou copiar grandes blocos da fonte.

## 5. Função de cada página

### `MASTER.md`

Página inicial da wiki. Deve explicar:

- qual edital foi indexado;
- quem é o órgão;
- qual é a banca;
- status do certame;
- o que a wiki conseguiu identificar;
- como navegar pelas páginas.

### `dados-principais.md`

Serve para identificar o certame. Deve conter órgão, edital, localidade, banca, status e observações de confiabilidade.

### `inscricoes.md`

Deve explicar período, forma de inscrição, taxa, pagamento, isenção, prorrogação e cuidados.

### `cargos-e-vagas.md`

Deve transformar o quadro de cargos em conhecimento. Primeiro explica a distribuição de oportunidades, depois mostra tabela quando houver segurança.

Se houver muitas linhas, pode resumir e apresentar tabela parcial. Nunca deve inventar cargo.

### `cronograma.md`

Deve reunir datas operacionais. Deve rejeitar datas jurídicas soltas.

### `provas-e-etapas.md`

Deve explicar tipo de prova, data, duração, disciplinas, quantidade de questões, pontuação e critérios de classificação.

### `conteudo-programatico.md`

Deve funcionar como guia de estudos, não como cópia integral do programa.

### `requisitos.md`

Deve organizar requisitos gerais, documentos, posse/contratação e requisitos específicos.

### `recursos.md`

Deve explicar quando cabe recurso, prazo, canal, fundamentação e cuidados formais.

### `retificacoes.md`

Deve explicar erratas, comunicados, prorrogações, suspensões e impacto prático.

## 6. Critérios de rejeição de página

Uma página deve ser rejeitada ou reescrita se:

- começar com bloco ```markdown;
- tiver cara de resposta de chatbot;
- só listar chunks;
- copiar blocos longos do edital;
- não tiver visão geral;
- não tiver fontes;
- confundir cargo com regra;
- confundir taxa com salário;
- confundir data jurídica com cronograma;
- não explicar o impacto para o candidato.

## 7. Modo sem LLM

Sem LLM ativa, o sistema pode gerar uma wiki determinística, mas ela deve ser marcada como qualidade baixa ou revisão necessária. Fallback não é sucesso; é modo degradado.

## 8. Objetivo final

O resultado esperado é uma wiki que permita ao candidato entender o edital sem ler o PDF inteiro, mas com rastreabilidade para conferir as fontes.

## 12. Regra da versão v20: LLM como microeditora, não autora da página inteira

A partir da v20, o agente não deve tentar escrever uma página completa recebendo milhares de caracteres de edital. Essa abordagem colapsa em modelos 7B/8B e costuma gerar cópia de texto bruto.

Fluxo correto da escrita:

```text
fatos estruturados pequenos
→ microcopy da LLM: introdução + leitura editorial + até 3 alertas
→ template Python monta a página completa
→ tabelas e fontes vêm dos dados validados
```

A LLM pode escrever:

- uma introdução curta de 3 a 5 frases;
- uma explicação de como interpretar os dados;
- pontos de atenção práticos.

A LLM não deve escrever:

- tabela completa de cargos;
- cronograma inteiro;
- schema público;
- página Markdown inteira;
- grandes blocos copiados do edital.

O Python é responsável por montar:

- títulos e seções;
- tabelas;
- listas de cargos;
- eventos do cronograma;
- taxas, salários e valores;
- fontes usadas.

Se a LLM falhar, o template ainda deve gerar uma página útil. Isso não é mais “fallback e fds”: é renderização determinística da wiki com qualidade controlada.
