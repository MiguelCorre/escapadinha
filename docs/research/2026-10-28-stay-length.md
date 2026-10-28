# Estadia por destino: quantas noites fazem sentido em cada destino com rotas ativas

*D52, 2026-10-28. Pesquisa de secretária sobre fontes de confiança (postos de turismo oficiais e
guias estabelecidos: Lonely Planet, Rough Guides, Rick Steves, Fodor's, Frommer's; onde nenhum
guia dá um número, o consenso dos fóruns dessas casas, assinalado como tal) para os 158
destinos com rotas ativas na tabela `routes` (cópia da base de dados do bucket, geração 305,
28/10/2026 13:51, última recolha #912), mais um backtest do detetor em modo só de leitura sobre
essa cópia (`scripts/backtest_detector.py --preset stays`, D44). Nenhuma chamada à API, nenhuma
alteração ao bucket. As tabelas de resultados são a saída do script; correr de novo para
as atualizar.*

**Motivo (Miguel, 2026-10-28):** as promoções devem respeitar a estadia que faz sentido para
cada destino. Se Paris é 3–4 dias, uma viagem de 10 noites a Paris não deve aparecer. Até aqui
o intervalo de noites vinha só do tipo da rota (`routes.kinds`: europe e domestic 2–10,
long_haul 7–21), igual para Paris e para a Madeira.

## Resumo

1. **Cada destino tem agora um intervalo de noites pesquisado**, em `config.yaml`
   `routes.overrides`, com a fonte na linha. O mecanismo é o que já existia: as exceções
   (`overrides`) passam a aceitar também um destino como chave ("PAR": todas as rotas para
   Paris), como as `exclusions` já aceitavam; uma chave de rota ("LIS-PAR") continua a ganhar à
   do destino. Nada de novo no detetor, na recolha ou no site: todos leem as regras da rota
   como antes.
2. **O intervalo molda tudo o que as regras da rota já moldavam**: a recolha (ofertas fora do
   intervalo não são guardadas), o preço habitual (só ofertas dentro do intervalo contam) e as
   duas camadas de publicação (preços baixos e candidatas a promoção). Decisão do Miguel
   (2026-10-28): não há um segundo mecanismo só para promoções.
3. **Backtest (14 dias, 14–27/10, 266 recolhas):** as candidatas caem de 220 para 108 (−51 %),
   os preços baixos por recolha de 60 para 34, os meses-rota maduros de 54 para 43. Das 142
   candidatas perdidas, 97 % ainda hoje seriam promoção; das 30 novas, 67 %. Quase metade das
   perdidas (47) são viagens curtas, de 2 a 4 noites: o preço habitual de um mês desce quando as
   viagens longas, mais caras, saem do intervalo, e uma viagem curta que era −30 % face a um
   habitual "inflacionado" por viagens de 8–10 noites deixa de o ser. É o efeito pretendido:
   comparar igual com igual.
4. **Deals abertos fora do novo intervalo expiram na reverificação seguinte** (`recheck.recheck`
   verifica as regras da rota antes do preço, com o motivo "fora do intervalo de 2–5 noites da
   rota"), aprovados incluídos: na cópia, LIS-PAR 9 noites e OPO-FNC 9 noites (aprovados) saem
   do site no primeiro caminho completo; LIS-FNC 5 e 7 noites, LIS-PAR 2 noites e OPO-MIL 3
   noites ficam.

## Método

- **Fontes.** Uma pesquisa por destino, limitada aos domínios dos guias (roughguides.com,
  lonelyplanet.com, ricksteves.com, fodors.com, frommers.com) e ao posto de turismo oficial
  quando o havia (turismolanzarote.com, visitmadeira.com, visitazores.com, hellocanaryislands.com,
  visitmalta.com, holland.com, germany.travel). A coluna "Fonte" da tabela liga à página usada.
  Quando nenhum guia dá um número (aeroportos regionais como Doncaster, Brive, Dole, Memmingen,
  Knock), a linha diz "no guide figure found" e usa o consenso do fórum do Rick Steves ou do
  Fodor's, ou a regra das ilhas pequenas (2–3 dias por ilha, Lonely Planet). Os postos de
  turismo raramente dizem "quantos dias"; publicam roteiros de "48 horas" ou "4 dias", que
  contam como recomendação.
- **Dias → noites.** A recomendação vem em dias; a regra da rota é em noites. Uma só regra,
  por tipo de destino, para que seja auditável:
  - cidades (europe e domestic): noites = [dias mín. − 1, dias máx.], nunca abaixo de 2 noites
    e com o máximo nunca abaixo de 3 (um fim de semana prolongado); Paris 3–5 dias → 2–5
    noites, uma viagem de 10 noites fica de fora;
  - praia e ilhas (europe e domestic): noites = [dias mín. − 1, 10]: as fontes falam em "uma
    semana ou mais" e 10 é o teto da recolha (D4); Madeira "pelo menos 4 dias" → 3–10;
  - cidades de longo curso: noites = [máx(4, dias mín.), dias máx. + 3]: a viagem é longa e
    uma escapadinha de 3 noites a Nova Iorque não é realista a partir de Portugal; Nova Iorque
    3–5 dias → 4–8;
  - praia e viagens longas de longo curso: noites = [máx(5, dias mín.), 14]: Maldivas "pelo
    menos 5 noites, uma semana se possível", Cabo Verde "uma semana ou 10 dias" → 5–14.
  O tipo de cada destino está na tabela. Mudar um número é mudar a linha em `config.yaml` (a
  fonte vai ao lado); mudar a regra é mudar esta nota e regenerar o bloco.
- **Backtest.** `uv run python scripts/backtest_detector.py <cópia> --preset stays --days 14`:
  o detetor configurado (D44) corrido duas vezes sobre as mesmas recolhas, uma com o intervalo
  do tipo em todas as rotas ("kinds only") e outra com os intervalos desta nota ("destination
  stays"), tudo o resto igual. A cópia é aberta `mode=ro` e copiada para memória.

## Backtest

Recolhas 23–792 (266 recolhas, 14 dias, 14/10–27/10). "Expired <= 24 h": a reverificação de preço
nas recolhas das 24 h seguintes expirou a candidata. "Holds today": ainda `threshold` e
`min_saving_eur` abaixo do preço habitual do mês-rota com tudo o que está guardado hoje, sem o
próprio dia da candidata.

| Rule set | Candidates (routes) | Per day | Expired <= 24 h | Holds today | New lows | Confidence | Low prices / run | Distinct low prices | Nights (median, max) |
|---|---|---|---|---|---|---|---|---|---|
| kinds only (the kind's nights range on every route) | 220 (11) | 15.71 | 211/220 (96%) | 210/220 (95%) | 220/220 (100%) | high 11, medium 209 | 60.2 | 1320 | 5, 10 |
| destination stays (D52) (config overrides: 333 of 375 routes differ) | 108 (8) | 7.71 | 105/108 (97%) | 96/108 (89%) | 108/108 (100%) | high 5, medium 103 | 34.3 | 795 | 4, 10 |

| Rule set | Kind | Candidates | Expired <= 24 h | Holds today | New lows | Distinct low prices |
|---|---|---|---|---|---|---|
| kinds only | domestic | 85 | 78/85 (92%) | 78/85 (92%) | 85/85 (100%) | 566 |
| kinds only | europe | 135 | 133/135 (99%) | 132/135 (98%) | 135/135 (100%) | 754 |
| destination stays (D52) | domestic | 51 | 49/51 (96%) | 41/51 (80%) | 51/51 (100%) | 353 |
| destination stays (D52) | europe | 57 | 56/57 (98%) | 55/57 (96%) | 57/57 (100%) | 442 |

**O que muda, candidata a candidata** (as duas listas comparadas por viagem e preço):

| | Perdidas (só "kinds only") | Novas (só "destination stays") |
|---|---|---|
| Candidatas | 142 | 30 |
| Por rota | OPO-PAR 56, OPO-FNC 50, OPO-MIL 19, OPO-BCN 7, LIS-PAR 5, OPO-LON 2, LIS-BCN 1, LIS-FNC 1, LIS-MAD 1 | OPO-PAR 11, OPO-FNC 10, LIS-FNC 7, LIS-PAR 2 |
| Por noites | 2: 17 · 3: 17 · 4: 13 · 5: 4 · 6: 6 · 7: 15 · 8: 20 · 9: 21 · 10: 29 | 2: 3 · 3: 8 · 4: 6 · 5: 1 · 6: 3 · 7: 1 · 8: 4 · 9: 1 · 10: 3 |
| Ainda promoção hoje | 138 de 142 (97 %) | 20 de 30 (67 %) |

- As 95 perdidas de 5 noites ou mais são o efeito direto: Paris passa a 2–5 noites, Milão a
  2–4, Barcelona a 2–5. As 47 perdidas de 2–4 noites são o efeito indireto no preço habitual
  (ponto 3 do resumo). As 30 novas vêm do mesmo efeito ao contrário: na Madeira (3–10 noites)
  as viagens de 2 noites saem do preço habitual e alguma viagem de 7–10 noites passa a ser
  −30 % face a um habitual mais baixo; é delas que vem a queda de "holds today" (89 % contra
  95 %), sobretudo em domestic (80 %).
- **Meses-rota** à data da cópia: com um dia contado 348 → 278; maduros para preços baixos
  (7 dias) 54 → 43; maduros para promoções (10 dias em 9) 31 → 27; confiança alta 11 → 10. As
  rotas para cidades perdem dias (menos ofertas por dia, D40 exige 2 datas de partida por dia),
  mas a maioria dos meses-rota que hoje publicam preços baixos continua madura.
- **Custo aceite:** cerca de metade das candidatas e dos preços baixos dos últimos 14 dias,
  quase todas viagens que os guias dizem ser demasiado longas (ou, nas ilhas, demasiado curtas)
  para o destino. Nenhuma candidata perdida é uma viagem que a tabela abaixo recomendaria.

## Deals abertos na cópia (28/10)

Aprovados: 17. Fora do novo intervalo do seu destino: **LIS-PAR 9 noites e OPO-FNC 9 noites**
(expiram na reverificação seguinte: "fora do intervalo de 2–5 noites da rota" / "… 3–10 …").
Dentro: LIS-FNC 5 e 7 noites (9 + 4 deals), LIS-PAR 2 noites, OPO-MIL 3 noites. Expirados: 383.

## Tabela: estadia recomendada por destino

As colunas: código do destino (como em `routes`), dias recomendados pela fonte, a fonte (ligação),
a nota do que a fonte diz, e as noites que `config.yaml` passa a usar. Os destinos sem entrada
em nenhum guia estão assinalados na nota ("no guide figure found").

### Cidades (europe e domestic): noites = [dias mín. − 1, dias máx.], nunca abaixo de 2–3

| Código | Destino | Dias recomendados | Fonte | Nota | Noites |
|---|---|---|---|---|---|
| ALG | Argel | 2–3 | [Lonely Planet, first-time guide to Algiers](https://www.lonelyplanet.com/articles/a-first-time-guide-to-algiers) | at least a couple of days; 2-3 for the essentials, 4-5 with Tipaza | 2–3 |
| AMS | Amesterdão | 3–5 | [Rough Guides](https://www.roughguides.com/articles/how-many-days-do-you-need-in-amsterdam-netherlands/) | 4-5 comfortable, 2-3 only with a tight schedule | 2–5 |
| ANK | Ancara | 2–3 | [Rough Guides, Ankara](https://www.roughguides.com/turkey/ankara/) | enough for a few days; Anıtkabir and the Anatolian Civilisations museum | 2–3 |
| ATH | Atenas | 2–4 | [Rough Guides, how many days in Athens](https://www.roughguides.com/greece/how-many-days-do-you-need-in-athens/) | 2-4 days, at least 3 full days, a 4th for Delphi/Sounion/Hydra | 2–4 |
| BCN | Barcelona | 3–5 | [Rick Steves Barcelona (pocket: a few days; full: a week)](https://www.hachette.co.uk/titles/rick-steves/rick-steves-barcelona-eighth-edition/9781641716895/) | guides cluster on 3-5 days, a week with Montserrat/Costa Brava | 2–5 |
| BEG | Belgrado | 2–4 | [Lonely Planet, the ultimate weekend in Belgrade (Friday to Monday)](https://www.lonelyplanet.com/articles/ultimate-weekend-belgrade-serbia) | 2-3 nights for the city, a 4th with Novi Sad | 2–4 |
| BER | Berlim | 3–5 | [Rick Steves, Berlin itinerary](https://ricksteves.com/europe/germany/berlin-itinerary) | itineraries for 1-7 days; 3 the common first-visit figure, 4-5 with Potsdam | 2–5 |
| BFS | Belfast | 1–3 | [Rick Steves, Ireland itinerary (one night and one full day in Belfast on the two-week plan)](https://www.ricksteves.com/europe/ireland/itinerary) | 2 full days comfortable, 3 nights with the Giant's Causeway | 2–3 |
| BHX | Birmingham | 2–4 | [Rough Guides, a weekend in Birmingham; Lonely Planet England itineraries (one day)](https://www.roughguides.com/england/how-to-spend-a-weekend-in-birmingham/) | 2-3 days for the city, 4 with Ironbridge/Stratford | 2–4 |
| BIO | Bilbau | 2–4 | [Lonely Planet, guide to Bilbao (3-4 days the sweet spot)](https://www.lonelyplanet.com/articles/guide-to-bilbao-spain) | 2 full days minimum, 4 with San Sebastián | 2–4 |
| BLK | Blackpool | 1–2 | [Lonely Planet, Blackpool Pleasure Beach; Fodor's forum (one night for the Illuminations)](https://lonelyplanet.com/england/northwest-england/blackpool/attractions/blackpool-pleasure-beach/a/poi-sig/1220337/358935) | 1 day, 1-2 nights | 2–3 |
| BLL | Billund | 2–3 | [Lonely Planet, the original Legoland (a day each for Legoland and Lego House, Lalandia a 3rd)](https://www.lonelyplanet.com/articles/guide-to-legoland-denmark) | 2 days, 3 with Lalandia/Ribe | 2–3 |
| BLQ | Bolonha | 2–4 | [Lonely Planet, first-time guide to Bologna (at least two days); Rough Guides (2-3)](https://www.lonelyplanet.com/articles/guide-to-bologna) | 2-3 days, 4 with Ravenna/Parma/Modena | 2–4 |
| BOD | Bordéus | 2–4 | [Rough Guides, 10 days in France (a day in Saint-Émilion); Rick Steves forum (2-3 days)](https://www.roughguides.com/articles/10-days-in-france-itinerary/) | 2 full days for the city, +1-2 for the vineyards/Arcachon | 2–4 |
| BRE | Bremen | 1–2 | [Rick Steves / Fodor's forums (one day for the old town, two with Bremerhaven); no guide figure found](https://community.ricksteves.com/travel-forum/germany/bremerhaven-and-environs) | 1 day for the old town, 2 nights with Bremerhaven | 2–3 |
| BRI | Bari | 3–5 | [Lonely Planet, guide to Bari (3 days at a relaxed pace, 5 with day trips)](https://www.lonelyplanet.com/articles/guide-to-bari) | 3 days for the city, 4-5 as a Puglia base | 2–5 |
| BRQ | Brno | 1–3 | [Lonely Planet, 24 hours in Brno; Frommer's (a day or two for the old centre)](https://www.lonelyplanet.com/articles/24-hours-in-brno) | 1 day for the city, 2-3 with Moravian day trips | 2–3 |
| BRS | Bristol | 2–3 | [Rough Guides, Bristol (worth more than a brief stop); Rick Steves forum (two days)](https://www.roughguides.com/england/bristol-bath-somerset/bristol/) | 2 full days, 3 with Bath/Wells | 2–3 |
| BRU | Bruxelas | 2–3 | [Rick Steves, where to go in Belgium (Brussels at the 4-day mark of a week)](https://www.ricksteves.com/europe/belgium/itinerary) | 2 full days, more as a base for Bruges/Ghent/Antwerp | 2–3 |
| BUD | Budapeste | 3–5 | [Rick Steves, Budapest itinerary (2 to 4 days)](https://www.ricksteves.com/europe/hungary/budapest-itinerary) | at least 3 days, 5+ with Eger/Szentendre; Lonely Planet: a long weekend | 2–5 |
| BUH | Bucareste | 2–4 | [Lonely Planet, Bucharest (a night or two is not enough: at least a few days)](https://www.lonelyplanet.com/destinations/romania/bucharest) | 2-3 full days, 3-4 relaxed | 2–4 |
| BVE | Brive | 1–2 | [Fodor's / Rick Steves forums (a day for the town; 4-5 days as a base for Corrèze/Lot/Dordogne); no guide figure found](https://www.fodors.com/community/europe/brive-la-gaillarde-spend-time-or-skip-912301/) | a day for the town, 4-7 as a Dordogne base | 2–3 |
| CCF | Carcassonne | 1–2 | [Rick Steves, France itinerary (two nights in Carcassonne on the three-week route)](https://www.ricksteves.com/europe/france/itinerary) | a one-day, one-night stop; 2 nights with Albi/Castres | 2–3 |
| CGN | Colónia | 2–3 | [Rick Steves Germany itinerary (a day trip for the cathedral); forum: 2-3 days with museums](https://www.ricksteves.com/europe/germany/itinerary) | 2 nights for the cathedral, Altstadt and museums, a 3rd for the Rhine | 2–3 |
| CMN | Casablanca | 2–3 | [Lonely Planet, first-time guide to Casablanca](https://www.lonelyplanet.com/articles/guide-to-casablanca) | two nights cover the highlights; a base for Rabat | 2–3 |
| CPH | Copenhaga | 3–5 | [Lonely Planet, things to know before Copenhagen](https://www.lonelyplanet.com/articles/things-to-know-before-traveling-to-copenhagen) | a small city known in 3 days; 4-5 with Roskilde/Kronborg/Louisiana | 2–5 |
| CTA | Catânia | 1–2 | [Frommer's, Catania (at least two full days)](https://www.frommers.com/destinations/catania/) | 1-2 days for the city, more with Etna/Syracuse/Taormina | 2–3 |
| CWL | Cardiff | 2–3 | [Rick Steves forum consensus (3 days for the castle, St Fagans, Caerphilly); no guide figure found](https://community.ricksteves.com/travel-forum/wales/3-days-in-cardiff) | 2 days for the city, 3 with day trips | 2–3 |
| DLE | Dole | 1–2 | [Fodor's forum (Dole a stop between Burgundy and Alsace; Burgundy 3 days min); no guide figure found](https://www.fodors.com/community/europe/burgundy-and-alsace-8-days-including-travel-days-908550/) | a one-night stop; 3 days as a Burgundy/Jura base | 2–3 |
| DRS | Dresden | 2–4 | [Lonely Planet, 4 days to learn about Dresden (the city in a day, a long weekend to learn it)](https://www.lonelyplanet.com/articles/dresden-four-day-itinerary) | 2-3 full days, 4 with Saxon Switzerland/Meissen | 2–4 |
| DSA | Doncaster | 1–2 | [Rough Guides, Yorkshire (no figure for Doncaster; a day, York 20 min away)](https://www.roughguides.com/england/yorkshire/) | 1 day; 2+ only with York/Yorkshire | 2–3 |
| DUB | Dublin | 2–4 | [Rough Guides](https://www.roughguides.com/ireland/how-many-days-do-you-need-in-dublin/) | 2 days for the essentials, 2-3 ideal, 4+ with Howth/Wicklow/Kilkenny | 2–4 |
| DUS | Düsseldorf | 1–3 | [Fodor's, what to do in Düsseldorf (a two-day plan)](https://www.fodors.com/world/europe/germany/the-rhineland/experiences/news/ask-fodors-what-should-i-do-in-dsseldorf-and-amsterdam-10478) | 1-2 days for the city, a 3rd for Cologne | 2–3 |
| EAP | Basileia-Mulhouse | 2–3 | [Rough Guides, Basel travel guide; Fodor's 5-day Switzerland itinerary starting in Basel](https://www.roughguides.com/switzerland/basel/) | 1.5-2 days for the Old Town and museums, a 3rd for Augusta Raurica | 2–3 |
| EBU | Saint-Étienne | 1–1 | [Rough Guides, Rhône Valley (museums; forum: a day trip from Lyon, 45 min by train)](https://www.roughguides.com/france/things-to-do-rhone-valley/) | a day; the kind floor of 2 nights applies | 2–3 |
| EDI | Edimburgo | 2–4 | [Rough Guides, how many days in Edinburgh (2 possible, 3 comfortable); Rick Steves (3 days)](https://www.roughguides.com/articles/how-many-days-do-you-need-in-edinburgh-scotland/) | 3 days, 4 with Rosslyn/South Queensferry | 2–4 |
| EIN | Eindhoven | 2–3 | [Rough Guides, Netherlands itineraries; Fodor's forum (a weekend, villages by bike); no Eindhoven figure in a guide](https://www.roughguides.com/netherlands/itineraries/) | a weekend for the city, 4-5 with the villages | 2–3 |
| EXT | Exeter | 1–4 | [Frommer's, two weeks in England; Rick Steves forum (a day for Exeter, 3-4 as a Devon base)](https://www.frommers.com/destinations/england/suggested-itineraries/in-two-weeks/) | 1 day for the cathedral city, 3-4 for Devon | 2–4 |
| FKB | Karlsruhe/Baden-Baden | 1–3 | [Rick Steves Germany itinerary (two nights in Baden-Baden for the spa)](https://www.ricksteves.com/europe/germany/itinerary) | 1-2 days in Baden-Baden, a day in Karlsruhe | 2–3 |
| FLR | Florença | 3–5 | [Rough Guides, how many days in Florence (3-4 comfortable); Lonely Planet (4-5)](https://www.roughguides.com/articles/how-many-days-do-you-need-in-florence-italy/) | 2 days for the main sights, 4 with Fiesole | 2–5 |
| FMM | Memmingen | 1–3 | [Rick Steves forum (a transit point; a couple of days as an Allgäu base for Füssen and the castles); no guide figure found](https://community.ricksteves.com/travel-forum/germany/stay-in-menningen-or-fussen) | 1-2 days for the town, 2-3 as a base for the Allgäu | 2–3 |
| FRA | Frankfurt | 1–3 | [Rick Steves Germany itinerary (a day in Frankfurt on arrival); forum: a couple of days at most](https://www.ricksteves.com/europe/germany/itinerary) | 1-2 days for the city, 3-4 with the Rhine/Heidelberg | 2–3 |
| GDN | Gdansk | 2–4 | [Rick Steves forum consensus (3-4 days, museums); no guide figure found](https://community.ricksteves.com/travel-forum/poland/how-long-for-gdansk-gdynia-sopot) | 2 full days for the city, 3-4 with Sopot/Gdynia/Malbork | 2–4 |
| GLA | Glasgow | 2–3 | [Frommer's, Glasgow in three days; Rick Steves Scotland itinerary](https://www.frommers.com/destinations/glasgow/suggested-itineraries/in-three-days/) | 2-3 full days, more with Stirling | 2–3 |
| GRQ | Groninga | 1–3 | [Rough Guides, Groningen: an ancient city with a young heart (a weekend break)](https://www.roughguides.com/articles/groningen-an-ancient-city-with-a-young-heart-in-the-netherlands/) | 1 day for the centre, 2-3 nights with museums | 2–3 |
| GVA | Genebra | 2–3 | [Lonely Planet, first-time guide to Lake Geneva (2-3 days on Geneva, 5 for the lake)](https://www.lonelyplanet.com/articles/guide-to-lake-geneva) | 1-2 days for the city, 5 with Lavaux/Chillon/Montreux | 2–3 |
| HAJ | Hanôver | 2–3 | [Rick Steves forum (a transit hub: 2-3 days, 5 with the Harz day trips); no guide figure found](https://community.ricksteves.com/travel-forum/germany/hanover-as-base) | 2-3 days as a stop, more as a base for Celle/Goslar | 2–3 |
| HAM | Hamburgo | 2–4 | [Rick Steves forum consensus (Europeans stay 3-4 days); no guide figure found](https://community.ricksteves.com/travel-forum/germany/how-many-days-in-hamburg) | 2 days for the highlights, 3-4 with Lübeck | 2–4 |
| HEL | Helsínquia | 2–3 | [Lonely Planet, Finland in a week (the city in two days)](https://www.lonelyplanet.com/articles/finland-in-a-week) | 2 full days, 3 with Porvoo or a Tallinn day trip | 2–3 |
| IST | Istambul | 3–5 | [Rough Guides, how many days in Istanbul](https://www.roughguides.com/turkey/how-many-days-do-you-need-in-istanbul/) | 3-4 days the recommendation, 2 at a run, a week for neighbourhoods | 2–5 |
| IZM | Esmirna | 2–4 | [Lonely Planet, 10 days in Türkiye (one day in Izmir); Fodor's forum (2 nights + Ephesus)](https://www.lonelyplanet.com/journeys/itineraries/85c714a0-202e-4456-9cbf-2f81018629ff) | 2 days for the city, 3 with Ephesus | 2–4 |
| KIR | Kerry | 2–3 | [Lonely Planet, one-week Ireland itinerary (two days in Killarney)](https://www.lonelyplanet.com/articles/ireland-luxury-hotels-dublin-adare-killarney) | 2 nights: the Ring of Kerry and Killarney National Park | 2–3 |
| KRK | Cracóvia | 2–5 | [Lonely Planet, first-time guide to Poland; a perfect weekend in Kraków](https://www.lonelyplanet.com/articles/perfect-weekend-in-krakow) | 2-3 days for the highlights, 4 with Auschwitz, 5 with the salt mine | 2–5 |
| KTW | Katowice | 1–2 | [Frommer's, Katowice planning a trip (an overnight stop, a day trip from Kraków)](https://www.frommers.com/destinations/katowice/planning-a-trip/) | 1-2 nights; a base for Auschwitz; the kind floor of 2 nights applies | 2–3 |
| LBA | Leeds | 1–2 | [Rick Steves forum (a half day to 1.5-2 days for a mid-sized city); no guide figure found](https://community.ricksteves.com/travel-forum/england/what-to-see-in-near-leeds) | 1-2 days; York 20 min away | 2–3 |
| LCG | Corunha | 1–3 | [Rough Guides, A Coruña / Northern Spain self-drive (the city in a day)](https://www.roughguides.com/spain/galicia/a-coruna/) | 1 day for the city, 2-3 nights with the coast/Santiago | 2–3 |
| LDY | Derry | 1–3 | [Rick Steves, Ireland itinerary (Derry at the 19-day mark); forum: a day for the city, 2-4 nights as a base](https://www.ricksteves.com/europe/ireland/itinerary) | 1 day for the walls and the Bogside, 2-3 nights with Inishowen | 2–3 |
| LEJ | Leipzig | 2–3 | [Rick Steves forum consensus (2-3 full days; Dresden a day trip); no guide figure found](https://community.ricksteves.com/travel-forum/germany/3-nights-in-dresden-or-leipzig) | 2 days passing through, 3 for music and 1989 history | 2–3 |
| LIL | Lille | 2–3 | [Lonely Planet, guide to Lille (a long weekend; the centre in two days)](https://www.lonelyplanet.com/articles/weekend-in-lille) | 2-3 days, 4+ with day trips or the braderie | 2–3 |
| LIS | Lisboa | 2–4 | [Rough Guides; Rick Steves Portugal itinerary (3 days Lisbon+Sintra)](https://www.roughguides.com/portugal/how-many-days-do-you-need-in-lisbon/) | 2 days for the highlights, 3 the baseline, 4 with Sintra/Cascais | 2–4 |
| LON | Londres | 3–6 | [Tourlane / Rick Steves London](https://www.tourlane.com/europe/england/how-many-days-in-london/) | 3 days the reasonable minimum, 4-6 comfortable, a week with day trips | 2–6 |
| LPL | Liverpool | 2–4 | [Lonely Planet, things to know before Liverpool (two days a taste, four the full works); Rough Guides](https://www.lonelyplanet.com/articles/things-to-know-before-traveling-to-liverpool) | 2 days for the highlights, 3-4 with the Beatles sights | 2–4 |
| LRH | La Rochelle | 2–4 | [Fodor's forum consensus (2 days the city, +1 for Île de Ré); no guide figure found](https://www.fodors.com/community/europe/how-many-days-in-the-cities-of-bordeaux-and-la-rochelle-1127716/) | 2 days for the town, 3-4 with Île de Ré/Rochefort | 2–4 |
| LUX | Luxemburgo | 2–4 | [Lonely Planet, first-time guide to Luxembourg](https://www.lonelyplanet.com/articles/first-time-guide-to-luxembourg) | a weekend for the city, 4 days with the Moselle and Esch, 7 with the Mullerthal | 2–4 |
| LYS | Lyon | 2–4 | [Rick Steves forum consensus (3 days most common, 3-4 nights with surroundings); no guide figure found](https://community.ricksteves.com/travel-forum/france/is-lyon-worth-a-visit-how-many-days-would-be-adequate) | 2 days for the sights, 3-4 with Pérouges/Vienne | 2–4 |
| MAD | Madrid | 2–4 | [Rough Guides](https://www.roughguides.com/spain/how-many-days-do-you-need-in-madrid/) | 2 days fast, 3 the sweet spot, 4-5 with Toledo/Segovia | 2–4 |
| MAN | Manchester | 2–4 | [Lonely Planet, 4 days in Manchester; the ultimate weekend](https://www.lonelyplanet.com/articles/manchester-four-day-itinerary) | a weekend to 4 days | 2–4 |
| MIL | Milão | 2–4 | [Rough Guides](https://www.roughguides.com/italy/how-many-days-do-you-need-in-milan/) | 2 days for the sights, 3 for depth, 4-5 with the lakes | 2–4 |
| MRS | Marselha | 2–4 | [Lonely Planet, things to know before Marseille (2-3 days, +1 for La Cité Radieuse)](https://www.lonelyplanet.com/articles/things-to-know-before-traveling-to-marseille) | 2-3 days for the city, a 4th for the Calanques/Cassis/Aix | 2–4 |
| MST | Maastricht | 1–2 | [Frommer's, two weeks in the Netherlands; forum: the highlights in a day, 2 days common](https://www.frommers.com/destinations/the-netherlands/suggested-itineraries/in-two-weeks/) | 1-2 days, a 3rd for Valkenburg/Aachen | 2–3 |
| MUC | Munique | 2–4 | [Rough Guides, how many days in Munich; Rick Steves Germany itinerary (3 days Munich + Alps)](https://www.roughguides.com/germany/how-many-days-do-you-need-in-munich/) | 2 days for the city, 3 recommended, a 4th for Neuschwanstein/Dachau | 2–4 |
| NAP | Nápoles | 3–4 | [Rough Guides, Naples (3-4 days cover the highlights, the 4th for Pompeii)](https://www.roughguides.com/italy/campania/naples/) | 3 days for the city, 4 with Pompeii, a week with the coast | 2–4 |
| NCL | Newcastle | 2–3 | [Rough Guides, Newcastle (Metro-linked sights as half-day extensions); Rick Steves forum (2-3 nights)](https://roughguides.com/destinations/europe/england/the-northeast/newcastle-tyne/nightlife) | 2 days for the city, +1-2 for Durham/Hadrian's Wall | 2–3 |
| NOC | Knock | 2–3 | [Rick Steves forum (2 nights in Westport, Knock a day trip); no guide figure found](https://community.ricksteves.com/travel-forum/ireland/noc-airport) | 2-3 nights in Westport/Mayo | 2–3 |
| NQT | Nottingham | 1–3 | [Frommer's, visiting Robin Hood's Nottingham; Lonely Planet England itineraries](https://www.frommers.com/slideshows/818435-on-location-visiting-robin-hood-s-nottingham/) | 1 day for the city, 2-3 with Sherwood/Newstead | 2–3 |
| NTE | Nantes | 1–3 | [Lonely Planet, France itineraries (Nantes: 1 day on the Atlantic route); best day trips from Nantes](https://www.lonelyplanet.com/articles/france-best-itineraries) | 1-2 days for the city, a 3rd for the coast | 2–3 |
| NUE | Nuremberga | 2–3 | [Rick Steves forum consensus (3 nights); Rough Guides Germany itineraries](https://community.ricksteves.com/travel-forum/germany/nurenberg-time-needed) | 2-3 full days with the WWII sites, a 4th for Bamberg/Rothenburg | 2–3 |
| OPO | Porto | 2–4 | [Rough Guides; Lonely Planet (a long weekend, 4 days / 3 nights)](https://www.roughguides.com/portugal/how-many-days-do-you-need-in-porto/) | compact: top sights in 2-4 days; a 4th day for the Douro | 2–4 |
| ORK | Cork | 2–3 | [Rough Guides, Cork travel guide (a couple of nights; Fota/Cobh a day trip)](https://www.roughguides.com/ireland/cork/) | 2 nights for the city with Kinsale/Cobh, more for West Cork | 2–3 |
| OSL | Oslo | 2–4 | [Lonely Planet, first-time guide to Oslo](https://www.lonelyplanet.com/articles/first-time-guide-oslo) | 2 days for the big hitters, 4 with Bygdøy and the fjord islands | 2–4 |
| OVD | Astúrias | 2–4 | [Rough Guides, 10 days in Northern Spain; Rick Steves forum (Oviedo 2 nights, Asturias 4-5 days)](https://www.roughguides.com/spain/itineraries/northern-spain-itinerary/) | 2 nights Oviedo, 4-5 for the region | 2–4 |
| PAR | Paris | 3–5 | [Rough Guides](https://www.roughguides.com/france/how-many-days-do-you-need-in-paris/) | 2 days = the headline sights at a run; guides converge on 3-5 for a first visit | 2–5 |
| PMO | Palermo | 3–4 | [Frommer's, Palermo (at least 3 days); Rough Guides (at least four)](https://www.frommers.com/destinations/palermo/things-to-do/) | 3-4 days with Monreale, +1 per day trip | 2–4 |
| POZ | Poznań | 2–3 | [Lonely Planet forum / Rick Steves forum (2 nights minimum, 3+ if possible)](https://www.lonelyplanet.com/thorntree/forums/europe-eastern-europe-the-caucasus/topics/how-many-days-do-you-need-for-poznan) | 2 full days, a 3rd with Gniezno | 2–3 |
| PRG | Praga | 3–5 | [Lonely Planet, perfect long weekend in Prague; Rick Steves Czech itinerary](https://www.ricksteves.com/europe/czech-republic/itinerary) | 3 days for the main sights, day trips from 4-5 | 2–5 |
| PSA | Pisa | 1–2 | [Rough Guides, Pisa (explored well in a day; two days to go beyond the square)](https://www.roughguides.com/italy/tuscany/pisa-around/) | 1-2 days; a Tuscany gateway (Lucca, Florence) | 2–3 |
| RAK | Marraquexe | 2–4 | [Rough Guides, how many days in Marrakesh](https://www.roughguides.com/articles/how-many-days-do-you-need-in-marrakesh-morocco/) | 2-4 days, 3-4 recommended, a 4th for the Atlas/Ourika | 2–4 |
| RBA | Rabat | 2–4 | [Lonely Planet, guide to Rabat](https://www.lonelyplanet.com/articles/guide-to-rabat-morocco) | 2 nights for the sites, a 4-night plan with Casablanca | 2–4 |
| RDZ | Rodez | 1–3 | [Rough Guides, Massif Central (Rodez needs no more than a day; Sauveterre a day trip)](https://www.roughguides.com/france/things-to-do-massif-central/) | 1 day for the town, 2-3 for the Aveyron/Gorges du Tarn | 2–3 |
| REK | Reiquiavique | 2–5 | [Lonely Planet, guide to Reykjavík (2-3 days + 2 for the countryside); Rough Guides 3 days](https://www.lonelyplanet.com/articles/guide-to-reykjavik) | 2-3 days for the city, +2 for the Golden Circle | 2–5 |
| RIX | Riga | 2–4 | [Lonely Planet, first-time guide to Latvia](https://www.lonelyplanet.com/articles/first-time-guide-to-latvia) | a weekend for Riga, 3 days comfortable, 4+ with Cēsis/Rundāle | 2–4 |
| RMO | Chisinau | 2–4 | [Lonely Planet, first-time guide to Moldova](https://www.lonelyplanet.com/articles/guide-moldova) | at least two days; a couple more for the wine cellars and Orheiul Vechi | 2–4 |
| ROM | Roma | 3–5 | [Rick Steves, Planning your time in Rome](https://www.ricksteves.com/watch-read-listen/read/articles/planning-your-time-in-rome) | 3-4 days minimum for the highlights, 5+ for neighbourhoods | 2–5 |
| RTM | Roterdão | 2–3 | [Rick Steves, where to go in the Netherlands (Rotterdam at days 7-9, with Leiden)](https://www.ricksteves.com/europe/netherlands/itinerary) | 2 full days with museums and the harbour, +1 for Kinderdijk/Delft | 2–3 |
| SOF | Sófia | 2–4 | [Frommer's, Bulgaria suggested itineraries (1-2 nights in Sofia)](https://www.frommers.com/destinations/bulgaria/suggested-itineraries/) | 2-3 days for the city, 4 with Rila/Boyana/Vitosha | 2–4 |
| SOU | Southampton | 1–2 | [Rick Steves forum ("good for a day or two"); a cruise port, day trips to Winchester/Salisbury](https://community.ricksteves.com/travel-forum/england/where-to-stay-and-explore-five-days-pre-cruise-departing-june-15-from-southampton) | 1-2 nights | 2–3 |
| STO | Estocolmo | 3–5 | [Frommer's, one week in Sweden; Rick Steves forum](https://www.frommers.com/destinations/sweden/suggested-itineraries/in-one-week/) | 3-4 full days for the highlights, 4-5 with the archipelago | 2–5 |
| STR | Estugarda | 1–2 | [Lonely Planet, 9-day Black Forest itinerary (day one in Stuttgart); forum: a day or two, 2 nights at the markets](https://www.lonelyplanet.com/articles/ultimate-9-day-itinerary-black-forest-germany) | 1-2 days; the car museums and Esslingen | 2–3 |
| SVQ | Sevilha | 3–4 | [Lonely Planet, things to know before Seville (three days the minimum)](https://www.lonelyplanet.com/articles/things-to-know-before-traveling-to-seville) | 2 days bare minimum, 3 comfortable, 4 with Córdoba | 2–4 |
| SXB | Estrasburgo | 2–4 | [Frommer's, two days in Strasbourg; Rough Guides (three or four days)](https://www.frommers.com/slideshows/848525-how-to-spend-two-days-in-strasbourg-the-proudly-french-city-that-looks-like-germany/) | 2 full days, 3 with Colmar | 2–4 |
| TLL | Tallinn | 2–4 | [Lonely Planet, guide to Tallinn](https://www.lonelyplanet.com/articles/guide-to-tallinn) | the Old Town in a day, 2 with Kadriorg, 3-4 with Lahemaa | 2–4 |
| TLS | Toulouse | 2–3 | [Lonely Planet, first-time guide to Toulouse (the heart in one packed day)](https://www.lonelyplanet.com/articles/guide-to-toulouse) | 2 full days, +1 each for Albi/Carcassonne | 2–3 |
| TNG | Tânger | 1–3 | [Lonely Planet, best Morocco itineraries (one day for Tangier); Rough Guides Tangier](https://www.lonelyplanet.com/articles/best-morocco-itineraries) | one full day passing through, two nights with Chefchaouen/Tetouan | 2–3 |
| TRN | Turim | 2–3 | [Lonely Planet, things to know before Turin (2-3 days for the key sights)](https://www.lonelyplanet.com/articles/things-to-know-before-traveling-to-turin) | 2-3 days, 4 with Rivoli/Venaria | 2–3 |
| TUF | Tours | 2–4 | [Rick Steves forum (three full days minimum for the Loire from Tours); Lonely Planet Loire road trips](https://community.ricksteves.com/travel-forum/france/how-to-see-the-loire-valley-without-a-car-from-the-city-of-tours) | 3-4 days for the Loire châteaux from Tours, 2 at a push | 2–4 |
| TUN | Tunes | 2–3 | [Lonely Planet, guide to Tunisia](https://www.lonelyplanet.com/articles/guide-to-tunisia) | 2-3 days for Tunis with Carthage and Sidi Bou Saïd; a week for the country | 2–3 |
| VCE | Veneza | 2–5 | [Rough Guides, how many days in Venice (2 for the highlights, 3 with Murano/Burano, 3-4 as a base)](https://www.roughguides.com/italy/how-many-days-do-you-need-in-venice/) | Lonely Planet: 5 days if time is tight | 2–5 |
| VIE | Viena | 3–5 | [Rick Steves Austria itinerary; Frommer's](https://www.ricksteves.com/europe/austria/itinerary) | 3 days in the itinerary; Frommer's: at least 4 | 2–5 |
| VLC | Valência | 2–4 | [Rough Guides, a weekend in Valencia (2-3 days for the highlights)](https://www.roughguides.com/spain/perfect-valencia-city-break/) | 3 days the common answer, 5 plenty | 2–4 |
| VNO | Vilnius | 2–4 | [Lonely Planet, first-time guide to Vilnius (at least a long weekend)](https://www.lonelyplanet.com/articles/first-time-guide-to-vilnius) | 2 full days, 3 with Trakai | 2–4 |
| WAW | Varsóvia | 2–4 | [Lonely Planet, first-time guide to Poland (two, better three, days for a city break)](https://www.lonelyplanet.com/articles/first-time-guide-to-poland) | 3 full days balanced, 4 with museums and a day trip | 2–4 |
| WRO | Breslávia | 2–3 | [Rick Steves forum consensus (2-3 days, 3 with the Churches of Peace)](https://community.ricksteves.com/travel-forum/poland/how-much-time-to-spend-in-polish-cities) | 2 days minimum, 3 the sweet spot, 4 with day trips | 2–3 |
| XCR | Châlons-en-Champagne | 1–2 | [Rick Steves, Reims: a bubbly day trip from Paris (Reims 1 day, 2 nights with a vineyard day)](https://www.ricksteves.com/watch-read-listen/read/articles/reims-a-bubbly-day-trip-from-paris) | no figure for Châlons itself; Champagne 1-2 days | 2–3 |
| ZRH | Zurique | 2–3 | [Lonely Planet, things to know before Zürich (compact: 2-3 days)](https://www.lonelyplanet.com/articles/things-to-know-before-traveling-to-zurich) | 2-3 days for the city, a 4th for Lucerne | 2–3 |

### Praia e ilhas (europe e domestic): noites = [dias mín. − 1, 10]

| Código | Destino | Dias recomendados | Fonte | Nota | Noites |
|---|---|---|---|---|---|
| ACE | Lanzarote | 4–7 | [Turismo Lanzarote (official), what to see in four days](https://turismolanzarote.com/en/what-to-see-in-lanzarote-in-four-days/) | four days enough for the island's main experiences; a week with La Graciosa | 3–10 |
| AGA | Agadir | 3–5 | [Lonely Planet, guide to Agadir](https://www.lonelyplanet.com/articles/guide-to-agadir) | a long weekend for the sights, +2 days for Taghazout/Paradise Valley; a beach resort | 2–10 |
| AGP | Málaga | 2–5 | [Lonely Planet, guide to Málaga (a weekend for the sights, 4-5 days relaxed, a week with day trips)](https://www.lonelyplanet.com/articles/first-time-guide-to-malaga) | 2-3 days for the city, a week on the coast | 2–10 |
| ALC | Alicante | 2–5 | [Lonely Planet, guide to Alicante (at least 2 nights; 4-5 as a Costa Blanca base)](https://www.lonelyplanet.com/articles/guide-to-alicante-spain) | 2 nights for the city, 4-5 with the coast | 2–10 |
| BOH | Bournemouth | 2–4 | [Lonely Planet England itineraries / Fodor's forum (two days, 3-4 with the Jurassic Coast)](https://www.lonelyplanet.com/articles/perfect-itineraries-england) | 2 days for the town, 3-4 with Dorset; a beach resort | 2–10 |
| CVU | Ilha do Corvo | 1–2 | [Lonely Planet, a guide to the Azores islands](https://www.lonelyplanet.com/articles/azores-islands-portugal) | the one island that fits a day; the kind floor of 2 nights applies | 2–10 |
| FAO | Faro | 2–7 | [Lonely Planet, guide to Faro (2-3 nights); Fodor's 3/5/7 days in the Algarve](https://www.lonelyplanet.com/articles/guide-to-faro-portugal) | Faro itself 2-3 nights; the Algarve 3-7 days | 2–10 |
| FLW | Ilha das Flores | 3–4 | [Lonely Planet, a guide to the Azores islands](https://www.lonelyplanet.com/articles/azores-islands-portugal) | three days, plus slack for weather-delayed flights | 2–10 |
| FNC | Madeira | 4–7 | [Lonely Planet, first-time guide to Madeira](https://www.lonelyplanet.com/articles/first-time-guide-to-madeira) | at least 4 days, sights spread over the island; +2 nights for Porto Santo | 3–10 |
| GRW | Ilha Graciosa | 2–2 | [Lonely Planet, a guide to the Azores islands](https://www.lonelyplanet.com/articles/azores-islands-portugal) | a two-day trip from Terceira, or a day trip | 2–10 |
| HOR | Horta | 2–4 | [Lonely Planet, a guide to the Azores islands (Faial/Pico/São Jorge by ferry)](https://www.lonelyplanet.com/articles/azores-islands-portugal) | 2-3 days each for Faial and Pico, São Jorge a day trip or short stay | 2–10 |
| IBZ | Ibiza | 4–10 | [Lonely Planet, first-time guide to Ibiza](https://www.lonelyplanet.com/articles/first-time-guide-to-ibiza) | 4 days the bare minimum, a week to 10 days ideal; a long weekend possible | 3–10 |
| LPA | Gran Canária | 3–7 | [Lonely Planet, guide to Gran Canaria](https://www.lonelyplanet.com/articles/guide-to-gran-canaria) | a long weekend, a week-long beach holiday or longer | 2–10 |
| MAH | Menorca | 4–7 | [Lonely Planet, first-time guide to Menorca](https://www.lonelyplanet.com/articles/guide-to-menorca) | at least a week to experience it properly; 3-4 days from one base | 3–10 |
| MLA | Malta | 3–7 | [Lonely Planet, things to know before Malta (7 days; Valletta alone 3); Fodor's (at least 4 with Gozo)](https://www.lonelyplanet.com/articles/things-to-know-before-traveling-to-malta/) | highlights in 7 days, 3-4 for the main sights | 2–10 |
| NCE | Nice | 3–5 | [Rough Guides, how many days in Nice (at least 3 full days, 5-7 with the coast)](https://www.roughguides.com/france/how-many-days-do-you-need-in-nice/) | 3 days for the city, 4 with Monaco/Villefranche/Antibes, a week at the beach | 2–10 |
| PDL | Ponta Delgada | 4–7 | [Lonely Planet, the ultimate week in the Azores; Fodor's trip reports (4-5 days on São Miguel)](https://www.lonelyplanet.com/articles/how-to-see-azores-in-a-week) | at least 4-5 days on São Miguel (weather) | 3–10 |
| PIX | Ilha do Pico | 2–4 | [Lonely Planet, a guide to the Azores islands](https://www.lonelyplanet.com/articles/azores-islands-portugal) | 2-3 days; an hour from Faial by ferry | 2–10 |
| PMI | Palma de Maiorca | 5–7 | [Lonely Planet, guide to Palma; the ultimate week in Mallorca](https://www.lonelyplanet.com/articles/ultimate-seven-day-itinerary-mallorca) | 5 days for Palma, a week with Sóller/Deià; 3 days workable but tight | 4–10 |
| PXO | Porto Santo | 2–7 | [Lonely Planet (at least 2 nights); Visit Madeira blog (4 days ideal)](https://visitmadeira.com/en/where-to-go/porto-santo/porto-santo/) | 2 nights minimum, 3-4 days for beaches and trails, a week to unwind | 2–10 |
| SJZ | Ilha de São Jorge | 2–3 | [Lonely Planet, a guide to the Azores islands](https://www.lonelyplanet.com/articles/azores-islands-portugal) | a day trip or a short stay from Faial/Pico | 2–10 |
| SMA | Santa Maria | 2–4 | [Lonely Planet, which Azores island should you visit (no own figure: the small-island rule, 2-3 days)](https://www.lonelyplanet.com/articles/best-places-to-visit-in-the-azores) | no specific count found; 2-3 days an island | 2–10 |
| TCI | Tenerife | 3–7 | [Lonely Planet, things to know before Tenerife ("a good few days")](https://www.lonelyplanet.com/articles/things-to-know-before-traveling-to-tenerife) | 3 days for the sights, 5-7 with the north, hikes and La Gomera | 2–10 |
| TER | Terceira | 2–4 | [Lonely Planet, 8 days Terceira to São Miguel](https://www.lonelyplanet.com/journeys/itineraries/7dc66df3-00b2-4c67-8ae4-58cb386ec260) | 2-3 days on Terceira in the two-island week | 2–10 |

### Cidades de longo curso: noites = [máx(4, dias mín.), dias máx. + 3]

| Código | Destino | Dias recomendados | Fonte | Nota | Noites |
|---|---|---|---|---|---|
| BOS | Boston | 3–4 | [Lonely Planet, things to know before Boston (a 3-day visit enough); Fodor's 4-day itinerary](https://www.lonelyplanet.com/articles/things-to-know-before-traveling-to-boston) | 3-4 days, Salem a day trip | 4–7 |
| DXB | Dubai | 3–7 | [Lonely Planet, first-time guide to Dubai (a week ideal); Frommer's (3 days possible, fast)](https://www.lonelyplanet.com/articles/first-time-guide-to-dubai) | 3 days rushed, 5 comfortable, a week with the desert/Abu Dhabi | 4–10 |
| MIA | Miami | 3–5 | [Lonely Planet, things to know before Miami (3 days a good minimum); Fodor's 3-day itinerary](https://www.lonelyplanet.com/articles/things-to-know-before-traveling-to-miami) | 1-2 days for the highlights, 3 minimum, 4+ with day trips | 4–8 |
| NYC | Nova Iorque | 3–5 | [Fodor's, NYC in a day or 5 (five days enough for much of the city); Frommer's 3-day itinerary; Lonely Planet weekend (3 nights)](https://www.fodors.com/world/north-america/usa/new-york/new-york-city/experiences/news/nyc-in-a-day-or-5-ultimate-itinerary-for-first-time-visitors) | a long weekend minimum, 5 days to see it reasonably well | 4–8 |
| SAO | São Paulo | 2–3 | [Lonely Planet, guide to São Paulo (a weekend; most iconic sights in 2-3 days, a week for museums and neighbourhoods)](https://www.lonelyplanet.com/articles/guide-to-sao-paulo) | 2-3 days for the sights | 4–6 |
| WAS | Washington | 3–4 | [Fodor's forum consensus (3-4 days for the monuments and a few museums, 5-7 leisurely); no guide figure found](https://www.fodors.com/community/united-states/how-much-time-needed-in-d-c-228354/) | at least 3, 4 covers the key spots | 4–7 |
| YMQ | Montreal | 3–4 | [Frommer's, Montreal in three days; Fodor's forum (3 full days first visit, 4-5 fuller)](https://frommers.com/destinations/montreal/in-three-days) | 2 days a taste, 3-4 first visit | 4–7 |
| YTO | Toronto | 3–4 | [Fodor's, 7 days in Toronto and Niagara; Fodor's forum (3 days minimum, 4 full days common)](https://www.fodors.com/world/north-america/canada/ontario/toronto/experiences/news/top-things-to-do-in-toronto-and-niagara-in-a-week) | 3-4 days, +1 for Niagara | 4–7 |

### Praia e viagens longas de longo curso: noites = [máx(5, dias mín.), 14]

| Código | Destino | Dias recomendados | Fonte | Nota | Noites |
|---|---|---|---|---|---|
| BKK | Banguecoque | 3–5 | [Rough Guides, 10 days in Thailand (2-3 days for the capital); Fodor's 3-day itinerary; forums 4-5 for first-timers](https://www.roughguides.com/thailand/itineraries/10-days-in-thailand-itinerary/) | 2-3 days quick, 4-5 first visit; usually with a beach or the north | 5–14 |
| BVC | Boa Vista | 5–10 | [Lonely Planet, guide to Cabo Verde (a week or 10 days for a beach holiday with excursions)](https://www.lonelyplanet.com/articles/guide-to-cabo-verde) | a beach week; 3-4 nights cover the dunes and 4x4 excursions | 5–14 |
| CPT | Cidade do Cabo | 4–7 | [Lonely Planet, things to know before Cape Town (most schedule 4-5 days, a week better); Rough Guides 5-7 with the Cape and winelands](https://www.lonelyplanet.com/articles/things-to-know-before-traveling-to-cape-town) | 4-5 days, 5-7 with Cape Point/Boulders/winelands, 10+ slow | 5–14 |
| CUN | Cancún | 3–7 | [Rough Guides, how many days in Cancún (2 at a resort, 4 with a Mayan site, 5-7 with MUSA/Contoy); Lonely Planet at least 3 nights](https://www.roughguides.com/mexico/how-many-days-do-you-need-in-cancun/) | 5-6 nights the common pattern, a week to 10 days for the Yucatán | 5–14 |
| FOR | Fortaleza | 3–7 | [Frommer's, Fortaleza (no more than a day in the city, then the beaches: Jericoacoara)](https://www.frommers.com/destinations/fortaleza/) | a day in town, several days on the Ceará coast; a 10-day trip samples several beaches | 5–14 |
| MLE | Maldivas | 5–7 | [Lonely Planet, things to know before the Maldives (at least 5 nights, a week if possible)](https://www.lonelyplanet.com/articles/things-to-know-maldives) | 5 nights minimum, a week; liveaboards 7-14 days | 5–14 |
| PUJ | Punta Cana | 4–7 | [Lonely Planet, best things to do in Punta Cana (a few days at a resort, full-day tours); Fodor's forum (7 days with 2 excursions)](https://www.lonelyplanet.com/articles/top-things-to-do-in-punta-cana) | 4-7 days: beach days plus one or two full-day tours | 5–14 |
| REC | Recife | 3–5 | [Frommer's, Brazil for families / Recife and Olinda (a day in Olinda, 2+ nights Porto de Galinhas)](https://www.frommers.com/destinations/recife-and-olinda/things-to-do/) | 1-2 days Recife/Olinda, 2-3 nights Porto de Galinhas | 5–14 |
| RIO | Rio de Janeiro | 4–5 | [Rough Guides, how many days in Rio (at least 4-5 days, 8-10 slow, a week at Carnival)](https://www.roughguides.com/brazil/how-many-days-do-you-need-in-rio-de-janeiro/) | 3 days enough for the city, 4-5 recommended, +day trips (Petrópolis, Búzios) | 5–14 |
| SID | Ilha do Sal | 7–10 | [Lonely Planet, guide to Cabo Verde (a week or 10 days for a beach holiday with excursions; Sal the resort hub)](https://www.lonelyplanet.com/articles/guide-to-cabo-verde) | a beach week; day trips from Santa Maria | 7–14 |
| SSA | Salvador | 2–4 | [Frommer's, suggested itineraries in Salvador (1 day rushed, 2 the old town and Barra, 3 a beach day, 4+ Morro de São Paulo/Chapada)](https://www.frommers.com/destinations/salvador/suggested-itineraries/) | 2-4 days for the city, more with the islands; Rough Guides 4 nights | 5–14 |
| TYO | Tóquio | 3–7 | [Rough Guides, how many days in Tokyo (at least 3, 5-7 with day trips); Lonely Planet (a week to slow down)](https://www.roughguides.com/japan/how-many-days-do-you-need-in-tokyo/) | 3-4 days minimum, 5-7 with Nikko/Kamakura | 5–14 |
