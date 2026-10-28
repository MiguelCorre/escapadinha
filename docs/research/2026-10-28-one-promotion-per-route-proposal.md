# Proposta: uma promoção por rota, com todas as datas baratas (rascunho para o Miguel decidir)

*2026-10-28. A terceira alteração às promoções, depois de D51 (sem limite diário) e D52
(estadia por destino). **Aceite pelo Miguel tal como está (2026-10-28) e implementada: DECISIONS D53.**
O backtest `--preset churn` (secção 6) foi corrido depois da aceitação. Os
números vêm da cópia da base de dados do bucket (geração 305, 28/10 13:51, última recolha
#912), lida em modo só de leitura. deferias.pt foi visto como uma pessoa (D13: duas páginas de
promoção lidas no browser, sem scraping).*

## 1. O problema, medido

- **400 deals, 383 desde 24/10, para 112 viagens distintas** (rota + ida + volta). 41 viagens
  tiveram um só deal; 71 tiveram dois ou mais; 3 tiveram 15 (OPO-PAR 8–10 dez, OPO-PAR 2–6 dez,
  LIS-PAR 8–11 dez). 374 dos 400 vêm da Ryanair (D47), cujos preços mexem aos cêntimos.
- **Porque expiram:** "o preço subiu" 216 (54 %), "a viagem já não aparece" 81, "já não é um
  novo mínimo" 67, preço habitual imaturo 7, já não abaixo do habitual 4, outros 8.
- **As subidas são minúsculas:** mediana 1,83 €; 92 de 216 subiram 1 € ou menos, 143 até 2 €,
  194 até 5 €; 143 (66 %) subiram 5 % ou menos, 201 (93 %) até 10 %. A tolerância 0 da
  reverificação (`recheck.tolerance_eur`) transforma cada oscilação de 1 € num deal expirado.
- **E voltam:** 277 deals nasceram numa viagem que já tinha um deal expirado (o detetor só
  bloqueia o mesmo preço ou mais alto entre deals abertos: `_already_flagged` +
  `recently_flagged_offers`, que ignora os expirados). Só 11 nasceram com um deal aberto na
  mesma viagem (mais barato). Vida de um deal expirado: mediana 7 h, um quarto dura menos de
  2 h 30, 43 morreram em menos de 1 h.
- **Hoje abertos (aprovados):** LIS-FNC 13 deals em 3 viagens (23–28 nov a 34,98 / 35,98 / 36,98 /
  37,98 €; 7–12 dez com cinco preços; 12–19 dez com quatro), LIS-PAR 2 (2–11 dez, que D52 vai
  expirar, e 9–11 dez), OPO-FNC 1 (24 nov–3 dez, 9 noites, idem), OPO-MIL 1. É o "mesma viagem
  duas vezes a preços diferentes" que a página inicial mostrou.

## 2. Como o deferias.pt apresenta (visto a 28/10)

Um artigo por destino e companhia, "desde €X ida e volta", com as rotas listadas (Porto – Veneza
Treviso – Porto; Lisboa – Veneza Treviso – Lisboa), cada rota com a sua ligação de reserva, e
as datas assim:

> Partida: 14, 15, 16, 22, 23, 25, 27, 29, 30 de Janeiro; 10, 18, 19, 24, 26, 27 de Fevereiro …
> Retorno: 24, 29 de Janeiro; 7, 8 de Fevereiro; 2 de Março …

ou só "Bons valores em Novembro – Janeiro" quando há muitas. Bagagem, companhia, hotel e seguro
a seguir. O artigo não muda depois de publicado ("os preços estão corretos no momento da
publicação"). Nós podemos fazer melhor: a página mostra as datas que **ainda** estão a esse
preço, cada uma com a sua observação (`data-obs`), e diz quando foi verificada.

## 3. Proposta

### 3.1 Modelo de dados: um deal continua a ser uma viagem; a promoção agrupa-os

- **`deals` fica como está**: uma linha = uma viagem (ida, volta) com a sua observação
  (`price_observations.id`, D2), o seu preço habitual, confiança, novo mínimo, reverificação. É
  o átomo rastreável; nada no site, nos eventos ou no snapshot deixa de apontar para ele.
- **Nova tabela `promotions`** (schema v18): `id`, `origin`, `destination`, `opened_at`,
  `closed_at`, `closed_reason`, e `deals.promotion_id` (nullable: deals antigos, e deals
  expirados antes de alguém aprovar, ficam sem promoção). **Uma promoção aberta por rota de
  cada vez** (decisão do Miguel: por rota, Lisboa → Paris e Porto → Paris separadas). Um
  candidato detetado junta-se à promoção aberta da sua rota; se não há nenhuma, abre uma. Uma
  promoção fecha quando não lhe resta nenhuma data válida; a próxima data barata da rota abre
  uma nova promoção (nova página; a antiga fica `noindex` e passa a 301 para a página da rota ao
  fim de `site.expired_promotions_days`, D35, como hoje).
- **O estado da promoção é derivado das datas**, não guardado: *ao vivo* se alguma data está
  aprovada/publicada e válida; *pública* (`website.is_public`) se alguma data foi alguma vez
  aprovada; *fechada* quando nenhuma data está aberta. Assim as decisões de revisão continuam a
  ser eventos por deal (D26), sem nova versão dos eventos.
- Rejeitado: promoção = deal "pai" com filhos (`deals.parent_id`): mistura os estados de uma
  viagem com os de um grupo, e a página teria de mudar de "pai" quando o pai expira.

### 3.2 Títulos, datas e preços na página

- **Título = a data mais barata válida** ("Voos diretos Lisboa → Paris desde 55 €"), com o
  `data-obs` dessa observação. Muda quando essa data expira ou chega uma mais barata; a
  página é reconstruída no caminho completo (a promoção entra em `run_path.fingerprint` via
  `site_data`, como tudo o que o site mostra).
- **Lista de datas** ao estilo deferias, mas uma linha por viagem: "ida 10 nov, volta 13 nov
  (3 noites) · 55 €" com `data-obs`, bagagem quando conhecida, companhia, e o botão de reserva
  de **cada** data (`cta.ts`: cada deal tem o seu `affiliate_url`/`deep_link`; na Ryanair a
  ligação é por datas, D47). Datas que expiram **saem** da lista (a página não mostra preços
  que já não existem; o registo fica no snapshot). Formatação só por `format.ts`/`dates.ts`.
- **O preço mostrado é sempre o último verificado**, com o `data-obs` da observação da
  reverificação (`deals.last_seen_price` já vem de uma observação guardada); "encontrado a …
  por 54,98 €" fica na ficha como história. Hoje a página mostra o preço da deteção; com a
  tolerância de 3.3 isso deixaria de ser honesto.

### 3.3 Reverificação e verificação ao vivo: por data, com tolerância; a promoção vive das datas

- **Uma data continua válida enquanto** (a) a viagem ainda aparece à sua fonte (D47), (b) o
  último preço está no máximo `recheck.tolerance_pct` (proposta: 5 %) acima do preço com que
  foi detetada **e** (c) esse preço ainda passa a regra de promoção contra o preço habitual
  guardado (`threshold` e `min_saving_eur`; `detector.evaluate`, como `promotion_expiry`). Na
  cópia, (b) sozinha teria evitado 143 das 216 expirações por subida.
- **Uma data expira** como hoje (razão em pt-PT, pipeline-owned, D26) e sai da promoção. **A
  promoção expira quando não lhe resta nenhuma data válida** (razão: "todas as datas expiraram;
  última: o preço subiu para 61 €").
- **Fim do pingue-pongue:** `recently_flagged_offers` passa a incluir os deals expirados da
  janela (`dedupe_days`) e `_already_flagged` só deixa voltar a sinalizar a mesma viagem se o
  novo preço for pelo menos `reflag_margin` (proposta: 5 %, mínimo 2 €) abaixo do preço do
  último deal dessa viagem, aberto ou expirado. 55 → 61 → 55 já não gera três deals; 61 → 52
  gera, e junta-se à promoção aberta da rota (ou abre uma).
- **Verificação ao vivo (aprovação, Function):** continua por data (`price_now` à fonte da
  data); aprovar uma promoção = aprovar cada data pendente que passa a verificação (um evento
  por deal, como hoje). A Function porta a mesma tolerância (`live-check-cases.json`, dos dois
  lados). Nada muda nos eventos (`contract/review/v1/event.schema.json`): sem v2.

### 3.4 Revisão e aprovação automática

- **Automática (D46, D51):** por data, com as regras de hoje e a verificação ao vivo como
  porta. A primeira data aprovada põe a promoção no site; cada data seguinte que passa as
  regras junta-se à página no caminho completo seguinte; uma que não passa espera por um humano
  na fila, debaixo da promoção.
- **Página de revisão (local e Function):** as datas agrupadas pela promoção da rota, a mais
  barata no topo, com os botões por data e um "aprovar todas / rejeitar todas" que emite um
  evento por data. **Rejeitar uma promoção** = rejeitar todas as datas abertas (a página fica
  `noindex`, sem botões). O snapshot ganha, por deal, `promotion: {id, path, dates: [deal ids]}`
  opcional, dentro da v1 pela exceção de D40 (a Function não valida o snapshot; um snapshot
  sem o campo mostra a fila de hoje).

### 3.5 Contrato do site: aditivo em v1 (recomendado) ou v2

- **Recomendo aditivo em v1:** `promotions.json` mantém um item por deal com todos os campos
  obrigatórios de hoje, e ganha `promotion: {id, path, lead: bool, dates: [deal ids]}`
  (opcional). O site constrói **uma página por promoção** a partir do item `lead` e lista as
  datas pelos itens membros; o `path` de cada item membro é o da promoção (é onde o deal se vê).
  A página inicial mostra um cartão por promoção. Um leitor antigo (fixtures, testes) continua
  a validar. Custo: um novo campo de preço? Não: cada data traz o `offer.eur` que já tinha, com
  o seu `obs`; nada novo a ensinar ao `test_site_data`.
- **v2** só se quisermos um item por promoção com as datas dentro: mais limpo, mas obriga a
  um segundo conjunto de esquemas, à regeneração das fixtures (adiada para #52) e a um
  cutover do site. Não vale a pena para isto.

### 3.6 Slugs e 301

- **Caminho da promoção:** `/promos/<origem>-<destino>-<promotion_id>/`? **Não**: colide com o
  padrão de hoje, `/promos/<deal_id>-<origem>-<destino>/`, e os ids das duas tabelas cruzam-se.
  Proposta: a promoção usa o **id do deal que a abriu** no slug de hoje,
  `/promos/<deal_id>-lisboa-paris/`, chave `deal:<id>` em `site.paths` como agora; os outros
  deals da promoção não têm página própria e os seus URLs antigos (os 17 aprovados de hoje, e
  qualquer deal que já tenha sido público) ganham uma regra 301 para a página da promoção
  (`website/redirects.py`, só para páginas construídas; `tests/test_crawl.py` prova que nenhum
  URL antigo dá 404). Quando a promoção fecha, o caminho segue D35.
- Alternativa: `promotion_id` próprio com prefixo `p` no slug (`/promos/p12-lisboa-paris/`).
  Funciona, mas são dois formatos de URL para sempre.

### 3.7 Fila de publicação (em pausa, mas correta)

- **Um post por promoção, não por data.** Só a primeira data aprovada de uma promoção enfileira
  posts (`plan_posts` no aplicador: nada quando a promoção da rota já tem posts em fila ou
  publicados). Uma data nova numa promoção já publicada não publica de novo.
- **O texto é construído na hora de enviar** (já é: `_message` em `run_publish`) a partir da
  promoção: título = a data mais barata válida nesse momento, e as outras datas em linhas
  "também: ida 12 dez, volta 15 dez · 58 €" (legenda e `whatsapp_text`, cada uma com a
  `DISCLOSURE`). A `posting_queue` ganha `promotion_id` (v18); `deal_id` fica como a data que
  a criou (as colunas e os estados do Instagram/Telegram não mudam).
- **Cancelamento:** quando a **promoção** expira ou é rejeitada, não quando a data que a criou
  expira e outras continuam. A reverificação antes do envio (`max_check_age_hours`) olha para a
  promoção. Slides: a renderização continua por deal; a promoção usa os slides do deal mais
  barato e a legenda acrescenta as outras datas (uma "slide de datas" fica para depois).

### 3.8 O que fica igual

Detetor puro (candidatos por viagem, `max_deals_per_route`), coletor, preços baixos e páginas
de rota, D52, o snapshot por deal (ganha um campo opcional), os eventos (iguais), os
publicadores (em pausa; nunca os ligo).

## 4. Decisões que são do Miguel

1. **Tolerância da reverificação:** 5 % do preço detetado (com a regra "ainda é promoção" por
   cima), ou outro valor? Com 5 %, 143 das 216 expirações por subida não teriam acontecido.
2. **Margem para voltar a sinalizar a mesma viagem:** 5 % (mín. 2 €) abaixo do último deal,
   mesmo expirado? Mata o pingue-pongue de 1 €; uma descida real (61 → 52) continua a entrar.
3. **Contrato:** aditivo em v1 (recomendo) ou v2.
4. **Slug:** o id do deal que abriu a promoção, formato de hoje (recomendo), ou ids próprios.
5. **Revisão por grupo:** "aprovar todas" / "rejeitar todas" na página além dos botões por
   data? E uma data que a aprovação automática recusou deve bloquear a promoção ou só ficar
   fora dela (proposta: só fora).
6. **Datas expiradas:** desaparecem da página (proposta) ou ficam riscadas.
7. **Posts:** uma promoção publica uma vez; as datas que chegam depois não republicam
   (proposta); ou um segundo post quando há uma data mais barata.
8. E a resposta que falta: **o que mais conta como "feito"** para as três alterações.

## 6. Backtest da margem e da tolerância (`--preset churn`, 14 dias, 14–27/10)

| Rule set | Candidates (routes) | Per day | Expired <= 24 h | Holds today | Confidence |
|---|---|---|---|---|---|
| no tolerance, no margin (before D53) | 279 (11) | 19.93 | 271/279 (97%) | 269/279 (96%) | high 14, medium 265 |
| tolerance only (rises up to 5 % hold) | 279 (11) | 19.93 | 270/279 (97%) | 269/279 (96%) | high 14, medium 265 |
| D53 (configured): tolerance 5 %, re-flag margin 5 % and 2 € | 133 (11) | 9.50 | 124/133 (93%) | 121/133 (91%) | high 7, medium 126 |

A margem corta as candidatas para metade (279 → 133, −52 %): as que saem são as repetições da
mesma viagem a menos 1–2 €. A tolerância quase não se vê aqui porque a aproximação de presença
do backtest (`run_id ≤ r ≤ last_run_id`, uma linha por preço) lê a maioria das mudanças de preço
como "a viagem já não aparece" (228 das 271 expirações no conjunto de base), não como "o preço
subiu"; a evidência para a tolerância é a distribuição de motivos em produção (secção 1: 216
subidas, 143 até 5 %). As expirações nas 24 h seguintes continuam altas (93–97 %) em qualquer
conjunto: as datas de uma promoção continuam a entrar e sair depressa; o que muda é que a página
deixa de ser substituída por uma nova a cada oscilação.

## 5. Ordem de implementação (um PR, ou dois)

1. Tolerância + margem de re-sinalização (puros: `recheck.py`, `detector.py`, config; backtest
   `--preset churn` a medir na cópia antes).
2. Tabela `promotions`, `deals.promotion_id`, o agrupamento na deteção, o estado derivado, a
   expiração da promoção (schema v18, migração testada de v5/v7/v17).
3. Exportação (`promotion` opcional em `promotions.json`), páginas (uma por promoção, cartão
   único na inicial), 301 dos URLs dos deals membros, snapshot + páginas de revisão, fila de
   publicação.
4. Docs: README, CLAUDE.md, DECISIONS D53, GLOSSARY ("Promoção" vs "Deal"), esta nota.
