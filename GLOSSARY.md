# Glossário

Vocabulário do projeto. Só conceitos do domínio; nada de implementação.

- **Observação** — um preço encontrado por um viajante numa data concreta, para uma viagem concreta (origem, destino, ida, volta), guardado com a hora em que o apanhámos e a fonte. Nunca inventamos uma observação. A mesma oferta vista em várias recolhas é uma só observação, com a primeira e a última vez que a vimos e quantas vezes a vimos.
- **Recolha** (run) — uma passagem do coletor por todas as rotas ativas. As respostas da fonte de cada recolha ficam arquivadas tal como vieram, para se poder provar de onde veio cada preço.
- **Rota** — um par origem → destino (ex.: Porto → Paris), independente das datas. Cada rota tem um *tipo* (Portugal, Europa ou longo curso), regras (só diretos ou número máximo de escalas, intervalo de noites) e um estado (ativa ou adormecida).
- **Regras da rota** — o que conta como oferta válida numa rota: só diretos ou até N escalas por sentido, e entre X e Y noites. Vêm do tipo da rota e podem ter exceções por rota. Ofertas fora das regras não entram no preço habitual nem são promoções.
- **Portugal** — rotas domésticas: de e para a Madeira e os Açores, entre ilhas e dentro do continente (ex.: Lisboa → Porto). No código: *domestic*. Substitui o rótulo antigo "Ilhas" (decisão do Miguel, 2026-10-13).
- **Descoberta** — a procura mensal, nos dados do fornecedor, de todas as rotas diretas que saem de Lisboa, Porto, Faro, Madeira, Ponta Delgada e Terceira, mais a lista escolhida de destinos de longo curso. Junta rotas novas e reativa as adormecidas que volta a encontrar; nunca apaga nenhuma.
- **Adormecida** — uma rota sem preços há 30 dias; deixa de ser consultada até a descoberta a voltar a encontrar. A página e o histórico mantêm-se.
- **Preço habitual** (no código: *typical low*) — a mediana dos mínimos diários de uma rota para um mês de partida. É o nível contra o qual se avalia um preço. Não é a média de todas as tarifas.
- **Preço baixo** — uma observação recente pelo menos 15 % abaixo do preço habitual da rota (só quando o preço habitual já tem dias de dados suficientes). Aparece automaticamente nas páginas de rota e no explorador, sem revisão humana, com a data em que foi encontrado e o seu próprio link de reserva.
- **Candidata a promoção** — um preço baixo pelo menos 30 % **e** pelo menos 15 € abaixo do preço habitual; no máximo uma por rota em cada recolha. Entra na fila de revisão do Miguel (estado "novo").
- **Promoção** (deal) — uma candidata que passou a revisão humana e é destacada (home, Instagram). Toda a promoção aponta para exatamente uma observação.
- **Decisão de revisão** (evento) — aprovar, rejeitar ou marcar como publicada uma promoção, registada por quem decidiu (Miguel no PC ou no telemóvel), com nota e hora. A decisão não muda nada sozinha: a recolha seguinte aplica-a, depois de confirmar que ainda faz sentido (ex.: uma promoção que entretanto expirou não pode ser aprovada). Enquanto não é aplicada, a decisão está **pendente**; uma decisão que já não faz sentido fica **recusada**, com o motivo.
- **Verificação ao vivo** — o preço da viagem consultado no momento, antes de aprovar. Se mudou, a aprovação é recusada.
- **Fila de revisão** — as candidatas à espera de decisão, mais as promoções aprovadas por publicar; é o que o Miguel vê no PC ou no telemóvel.
- **Expirada** — uma promoção cujo preço já não se confirma (subiu, desapareceu, deixou de ser direto ou está demasiado antigo). Mantém-se visível como histórico, sem botão de reserva.
- **Explorador** — a pesquisa sobre o nosso histórico: "para onde posso ir desde X por menos de Y €", mês mais barato por rota. Mostra preços encontrados, não preços ao vivo.
- **Pesquisa ao vivo** — o widget do parceiro (Aviasales) para procurar voos com preços atuais; a reserva faz-se no parceiro.
- **Roteiro** — um plano de viagem para um destino (ex.: 3 dias em Roma), escrito por nós e revisto antes de ir ao ar.
- **Dica** — um artigo prático e intemporal sobre viajar (bagagem, seguros, eSIM…), também revisto antes de ir ao ar.
- **Guia** — termo antigo do protótipo para o carrossel "guia rápido" no Instagram; é uma dica em formato de slides.
- **Longo curso** — destinos fora da Europa/Norte de África, normalmente com escala; têm critérios de promoção próprios.
