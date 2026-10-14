# Rever roteiros e dicas antes de publicar

Guia passo a passo para o Miguel (issue #19, decisões D33 e D37). Os roteiros e as dicas são
ficheiros MDX em `web/src/content/itineraries/` e `web/src/content/tips/`. Os rascunhos do Claude
chegam sempre com `reviewed: false`: o site não os constrói nem os lista, e só aparecem no
servidor local, com o aviso "Rascunho". Só tu mudas um ficheiro para `reviewed: true`.

## Rascunhos à espera de revisão (#19)

| Ficheiro | Página no servidor local |
|---|---|
| `itineraries/barcelona-em-3-dias.mdx` | `/roteiros/barcelona-em-3-dias/` |
| `itineraries/paris-em-4-dias.mdx` | `/roteiros/paris-em-4-dias/` |
| `itineraries/roma-em-3-dias.mdx` | `/roteiros/roma-em-3-dias/` |
| `itineraries/madeira-em-3-dias.mdx` | `/roteiros/madeira-em-3-dias/` |
| `itineraries/sao-miguel-em-3-dias.mdx` | `/roteiros/sao-miguel-em-3-dias/` |
| `tips/bagagem-de-mao.mdx` | `/dicas/bagagem-de-mao/` |
| `tips/esim-ou-roaming.mdx` | `/dicas/esim-ou-roaming/` |
| `tips/seguro-de-viagem.mdx` | `/dicas/seguro-de-viagem/` |
| `tips/transportes-aeroportos.mdx` | `/dicas/transportes-aeroportos/` |
| `tips/direitos-dos-passageiros.mdx` | `/dicas/direitos-dos-passageiros/` |
| `tips/voos-baratos.mdx` (o antigo "guia rápido", #17, ainda sem fontes) | `/dicas/voos-baratos/` |

## 1. Abrir os rascunhos no browser

- [ ] Na pasta do projeto: `cd web`.
- [ ] Na primeira vez (ou depois de um `git pull` que mude o `package-lock.json`): `npm ci`.
- [ ] `npm run dev:fixtures` e abre http://localhost:4321/roteiros/ e http://localhost:4321/dicas/
      (as listagens mostram os rascunhos). O servidor usa os dados de teste do contrato, por isso
      a ligação ao hub do destino só aparece para cidades que existem nesses dados (Paris,
      Barcelona, Madeira); o texto do artigo é o verdadeiro.
- [ ] Também podes usar os dados reais: `uv run escapadinha store pull` e
      `uv run escapadinha export site-data --no-new-links` na raiz do projeto (escreve
      `web/src/data` sem criar ligações novas) e depois `npm run dev` em `web/`.
- [ ] Os blocos de afiliados (eSIM, atividades, seguro) **não aparecem** nos rascunhos: um
      rascunho ainda não tem ligação de afiliado (só é criada depois de aprovado) e o seguro ainda
      não tem programa. O terminal mostra uma linha `[affiliates] … block not shown` por bloco.
      Vê onde estão no ficheiro (`<EsimBlock />`, `<ActivitiesBlock />`, `<InsuranceBlock />`).
- [ ] O servidor atualiza a página sempre que gravas o ficheiro. Para parar: `Ctrl+C`.

## 2. O que verificar em cada rascunho (cerca de 15 minutos cada)

- [ ] **Notas para ti:** no topo do ficheiro, entre os `---`, as linhas que começam por
      `# TODO Miguel` dizem o que não consegui confirmar ou o que precisa de decisão tua. Resolve
      cada uma e apaga a linha.
- [ ] **Factos:** abre cada fonte da lista `sources` e confirma cada frase do texto (horários,
      linhas de transporte, regras, distâncias, dias de fecho). Se uma frase não estiver na
      fonte, corta-a ou acrescenta uma fonte oficial que a confirme (`title` + `url` em https).
      Cada artigo tem pelo menos três fontes oficiais.
- [ ] **Preços:** não pode haver nenhum (nem "€", nem "EUR", nem "euros"). Os preços vêm só dos
      dados do site, com a sua observação. O teste `npm test` falha se aparecer algum.
- [ ] **Tom e português:** português de Portugal, a tratar o leitor por "tu", frases curtas. O
      teste de pt-PT apanha "você", palavras do Brasil, datas em inglês ou com números ao
      contrário e "3.5" em vez de "3,5", mas não apanha tudo: lê em voz alta.
- [ ] **Blocos de afiliados:** fazem sentido onde estão? O bloco tem de estar também na lista
      `affiliates:` do topo (senão a construção do site para). Se não quiseres um bloco, apaga a
      linha do bloco **e** o nome na lista.
- [ ] **Meses (só roteiros):** `best_months` ficou vazio de propósito (não encontrei uma fonte
      oficial que diga quais são os melhores meses). Podes preenchê-lo tu, se quiseres (é
      opcional), com os números dos meses: por exemplo `best_months: [4, 5, 9]` aparece na página
      como "abril, maio e setembro".

## 3. Aprovar

- [ ] No topo do ficheiro, muda `reviewed: false` para `reviewed: true` (mesmo assim, em
      minúsculas; `yes` não serve).
- [ ] Muda `last_checked:` para o dia em que confirmaste os factos, no formato `2026-10-20`.
- [ ] Em `web/`, corre `npm test` (inclui o teste de pt-PT e a construção do site).
- [ ] Faz commit e push para o `master` (ou um PR). A próxima execução do pipeline vê a mudança,
      publica a página (`/roteiros/...` ou `/dicas/...`), põe-na nas listagens e no início do
      site, e cria as ligações de afiliado dos blocos listados.

## Devolver com notas

Se um rascunho não estiver pronto, deixa `reviewed: false` e escreve as notas num comentário da
issue #19 (ou diretamente no ficheiro, em linhas `# ...` no topo). Um rascunho nunca chega ao site.
