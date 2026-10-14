# Glossário

Vocabulário do projeto. Só conceitos do domínio; nada de implementação.

- **Observação** — um preço encontrado por um viajante numa data concreta, para uma viagem concreta (origem, destino, ida, volta), guardado com a hora em que o apanhámos e a fonte. Nunca inventamos uma observação. A mesma oferta vista em várias recolhas é uma só observação, com a primeira e a última vez que a vimos e quantas vezes a vimos.
- **Recolha** (run) — uma passagem do coletor por todas as rotas ativas. As respostas da fonte de cada recolha ficam arquivadas tal como vieram, para se poder provar de onde veio cada preço.
- **Caminho rápido / caminho completo** (fast path / full path) — cada recolha de 2 em 2 horas só recolhe, reverifica e deteta (caminho rápido); gerar slides, construir e publicar o site (caminho completo) só acontece quando algo que o site mostra mudou (promoções, preços baixos, rotas, o dia) ou quando o Miguel o pede.
- **Rota** — um par origem → destino (ex.: Porto → Paris), independente das datas. Cada rota tem um *tipo* (Portugal, Europa ou longo curso), regras (só diretos ou número máximo de escalas, intervalo de noites) e um estado (ativa ou adormecida).
- **Regras da rota** — o que conta como oferta válida numa rota: só diretos ou até N escalas por sentido, e entre X e Y noites. Vêm do tipo da rota e podem ter exceções por rota. Ofertas fora das regras não entram no preço habitual nem são promoções.
- **Portugal** — rotas domésticas: de e para a Madeira e os Açores, entre ilhas e dentro do continente (ex.: Lisboa → Porto). No código: *domestic*. Substitui o rótulo antigo "Ilhas" (decisão do Miguel, 2026-10-13).
- **Descoberta** — a procura mensal, nos dados do fornecedor, de todas as rotas diretas que saem de Lisboa, Porto, Faro, Madeira, Ponta Delgada e Terceira, mais a lista escolhida de destinos de longo curso. Junta rotas novas e reativa as adormecidas que volta a encontrar; nunca apaga nenhuma.
- **Adormecida** — uma rota sem preços há 30 dias; deixa de ser consultada até a descoberta a voltar a encontrar. A página e o histórico mantêm-se.
- **Preço habitual** (no código: *typical low*) — a mediana dos mínimos diários de uma rota para um mês de partida. É o nível contra o qual se avalia um preço. Não é a média de todas as tarifas.
- **Preço médio** (no código: *average*) — a média simples dos mesmos mínimos diários que dão o preço habitual. Só aparece como contexto nas páginas de rota; nunca serve para decidir se um preço é baixo ou promoção.
- **Preço baixo** — uma observação recente pelo menos 15 % abaixo do preço habitual da rota (só quando o preço habitual já tem dias de dados suficientes). Aparece automaticamente nas páginas de rota e no explorador, sem revisão humana, com a data em que foi encontrado e o seu próprio link de reserva.
- **Candidata a promoção** — um preço baixo pelo menos 30 % **e** pelo menos 15 € abaixo do preço habitual; no máximo uma por rota em cada recolha. Entra na fila de revisão do Miguel (estado "novo").
- **Promoção** (deal) — uma candidata que passou a revisão humana e é destacada (home, Instagram). Toda a promoção aponta para exatamente uma observação.
- **Decisão de revisão** (evento) — aprovar, rejeitar ou marcar como publicada uma promoção, registada por quem decidiu (Miguel no PC ou no telemóvel), com nota e hora. A decisão não muda nada sozinha: a recolha seguinte aplica-a, depois de confirmar que ainda faz sentido (ex.: uma promoção que entretanto expirou não pode ser aprovada). Enquanto não é aplicada, a decisão está **pendente**; uma decisão que já não faz sentido fica **recusada**, com o motivo.
- **Verificação ao vivo** — o preço da viagem consultado no momento, antes de aprovar. Se mudou, a aprovação é recusada.
- **Fila de revisão** — as candidatas à espera de decisão, mais as promoções aprovadas por publicar; é o que o Miguel vê no PC ou no telemóvel.
- **Expirada** — uma promoção cujo preço já não se confirma (subiu, desapareceu, deixou de ser direto ou está demasiado antigo). Mantém-se visível como histórico, sem botão de reserva.
- **Explorador** — a pesquisa sobre o nosso histórico: "para onde posso ir desde X por menos de Y €", com filtros de orçamento, mês, noites, só diretos, fins de semana e pontes. Mostra cada destino pelo seu preço baixo mais barato; são preços encontrados, não preços ao vivo.
- **Fim de semana** (no explorador) — uma viagem com ida à sexta ou ao sábado e volta no domingo ou na segunda-feira seguintes.
- **Feriado** — um feriado nacional (Código do Trabalho, art. 234.º). A Terça-Feira de Carnaval é facultativa (art. 235.º): nem todos têm o dia livre. Os feriados municipais não contam.
- **Ponte** — o fim de semana prolongado que um feriado dá: à segunda ou à sexta junta um dia ao fim de semana; à terça ou à quinta junta dois, tirando o dia útil do meio (a "ponte" propriamente dita). Um feriado à quarta, ao sábado ou ao domingo não dá ponte. Um preço baixo serve uma ponte quando a ida é entre a véspera do primeiro dia livre e o feriado, e a volta entre o feriado e o dia a seguir ao último dia livre.
- **Pesquisa ao vivo** — o widget do parceiro (Aviasales) para procurar voos com preços atuais; a reserva faz-se no parceiro.
- **Roteiro** — um plano de viagem para um destino (ex.: 3 dias em Roma), escrito por nós e revisto antes de ir ao ar.
- **Dica** — um artigo prático e intemporal sobre viajar (bagagem, seguros, eSIM…), também revisto antes de ir ao ar.
- **Guia** — termo antigo do protótipo para o carrossel "guia rápido" no Instagram; é uma dica em formato de slides.
- **Longo curso** — destinos fora da Europa/Norte de África, normalmente com escala; têm critérios de promoção próprios.
- **Aviso de publicidade** (disclosure) — a frase que diz que os links de reserva são de afiliado e que podemos receber uma comissão sem custo extra. Tem duas versões, sempre palavra por palavra: a do site, ao lado de cada botão de reserva, e a dos posts, em cada legenda e no slide final. Onde há botão de reserva há aviso.
