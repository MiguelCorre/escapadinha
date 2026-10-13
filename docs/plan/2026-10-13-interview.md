# Entrevista de planeamento — 13/10/2026

Decisões tomadas por Miguel (Ronda 1):

- D-R1.1 Cobertura: todas as rotas diretas desde LIS, OPO, FAO, FNC, PDL (descoberta automática), depois ~20 destinos de longo curso com escala e critério próprio. `direct_only` passa a ser por rota.
- D-R1.2 Baseline = preço habitual (mediana dos mínimos diários por rota+mês). Média só como contexto.
- D-R1.3 Procurar voos = Explorador sobre o nosso histórico (produto) + widget Aviasales (complemento).
- D-R1.4 Roteiros e dicas: Claude rascunha, Miguel revê/aprova. Um roteiro por destino, só para destinos com promoções publicadas. Notícias fora.
- D-R1.5 Monetização: afiliados de voos agora; eSIM + seguro + atividades nos roteiros; hotéis/pacotes só com tráfego; ads só >10k visitas/mês e nunca na página de promoção.
- D-R1.6 Site migra para Astro + Tailwind com design system próprio; Python continua a ser o pipeline de dados e produz um contrato JSON.
- D-R1.7 Nome e domínio: nome FECHADO a 2026-10-13 → **Ponto Nómada** (tagline "A Nocas pelo mundo, o mundo ao teu alcance."; esboço da partner do Miguel). Domínio .pt por registar (issue #22); handle IG muda mais tarde.
- D-R1.8 Dois níveis de publicação: preços baixos automáticos nas páginas de rota/explorador; Promoções (home, Instagram) com aprovação humana.

Ronda 2:

- D-R2.1 Longo curso: ≤1 escala por sentido, 7–21 noites, lista de 20 destinos (NYC, MIA, YTO, SAO, RIO, DXB, BKK, TYO, SEL, DPS, CUN, CPT, MLE, NBO, BUE, HAV, PUJ, HAN, SIN, SYD), só desde LIS/OPO.
- D-R2.2 Origens: LIS, OPO, FAO, FNC, PDL, TER. Domésticos entram como categoria "Ilhas".
- D-R2.3 Rotas redescobertas mensalmente; dormentes após 30 dias sem observações; nada é apagado.
- D-R2.4 Instagram: NADA é publicado sem aprovação de Miguel. O sistema sugere (fila de aprovação); aprovado → fila de publicação com horários fixos (até 3 posts/dia) + story; deal que expira antes de sair é retirado.
- D-R2.5 Canais: Telegram automático (após aprovação); WhatsApp com texto copy-paste gerado por promoção para Miguel colar à mão; newsletter semanal quando ≥10 roteiros.
- D-R2.6 Arquitetura de páginas: /, /promocoes/, /voos/<o>-<d>/, /voos-desde/<o>/, /destinos/<cidade>/, /explorar/, /roteiros/, /dicas/, /sobre/, /privacidade/, /contacto/.
- D-R2.7 Explorador: origem, orçamento, mês, só diretos, noites, fins de semana, pontes e feriados PT (calendário no repo) + páginas SEO por ponte.
- D-R2.8 Métricas: Cloudflare Web Analytics + Travelpayouts por sub_id. Sem cookies/banner.
- D-R2.9 Design em HTML real: 3 direções → escolha → design system → Astro. Logo provisório SVG; designer opcional quando o nome fechar.

Ronda 3:

- D-R3.1 Pipeline sem custos: GitHub Actions (cron 2h; repo privado, 2000 min/mês — passo rápido só de recolha, render/site só quando há novidades) + base SQLite guardada em Cloudflare R2 entre runs (payloads brutos comprimidos em R2, não no SQLite; observações deduplicadas). Fila de aprovação passa a Cloudflare Pages Function protegida por Cloudflare Access (aprovar do telemóvel); decisões gravadas como eventos append-only em R2, aplicadas pelo run seguinte. Task Scheduler do PC fica como fallback até o Actions estar provado. Rejeitados: Oracle Always Free (reclamação de VMs ociosas, signup instável), GCP e2-micro (cartão + risco de egress), VPS pago.
  Fallback se o R2 exigir cartão e Miguel não quiser: DB no cache do Actions + snapshot semanal em GitHub Release.
- D-R3.2 Ordem: M1 dados em escala → M2 design (paralelo) → M3 site Astro → M4 conteúdo → M5 distribuição → M6 marca; M6 (nome/domínio) decidido antes de M3 ir ao ar.
- D-R3.3 Lista de ações de Miguel aceite (GitHub, Cloudflare R2/Access/Analytics, Travelpayouts projeto site, direção visual, revisão de conteúdo, Meta app, Telegram, nome/domínio/logo, aprovações). ~1 h/semana. Pergunta Facebook/Página FB em aberto → resolver no ticket M5.
- D-R3.4 Critérios de feito: testes verdes; nenhum preço sem observação (teste); pt-PT revisto; Lighthouse mobile ≥ 90; docs no mesmo commit; tickets independentes ≤ meio dia com verificação e secção "Ações do Miguel".
- D-R3.5 Monorepo: src/escapadinha (Python) + web/ (Astro); Python gera web/src/data/*.json.
