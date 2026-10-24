# Vendor e-mails: OAG/Infare, Skyscanner Data Products, Duffel sales

*Drafts, 2026-10-24, from sections 2.1–2.3 of
[`2026-10-24-faster-deal-discovery.md`](2026-10-24-faster-deal-discovery.md). **Nothing has been
sent.** Miguel sends them himself (DECISIONS D46: a new price source is his call; D13 stands
until he says otherwise). Written in English because all three vendors are international sales
teams.*

**Antes de enviar (pt-PT, para o Miguel):**

- Preenche `[nome completo]`, `[entidade]` (nome próprio, empresa ou "sole trader", conforme o
  caso) e `[e-mail]`. Envia a partir de um endereço do domínio `pontonomada.pt` se tiveres um: estas
  equipas filtram remetentes de Gmail.
- Os números dos e-mails vêm do relatório e da base de dados: 6 aeroportos de origem, 375 rotas
  diretas, 7 845 observações na cópia de 2026-10-20, 43 % das observações em Ryanair + Wizz Air.
  Se o relatório estiver desatualizado quando enviares, ajusta.
- Onde enviar: OAG através do formulário de contacto da página
  [Retailer PPS](https://www.oag.com/retailer-pps); Skyscanner através do
  [contacto de parceiros](https://www.partners.skyscanner.net/contact/travel-api) pedindo
  encaminhamento para Data Products; Duffel através do botão "Talk to sales" em
  [duffel.com/pricing](https://duffel.com/pricing). Não há endereços de e-mail públicos confirmados;
  se o formulário tiver limite de caracteres, cola só os parágrafos "What we would like" e "Questions".
- Não prometas volumes nem assines nada por e-mail: pede proposta e minuta de contrato. A decisão
  sobre o D13 (secção 3 do relatório: o link vai para quem vende a tarifa) só precisa de estar
  tomada antes de assinar, não antes de perguntar.

---

## 1. OAG / Infare (Retailer PPS or Altus: fare alerts with publishing rights)

**Subject:** Fare alerts from Portugal (375 routes) with rights to publish — quote and pilot

Hello,

I run pontonomada.pt, a Portuguese flight-deals website. We track round-trip fares on every
direct route from Lisbon, Porto, Faro, Madeira, Ponta Delgada and Terceira (375 routes, plus
about 20 long-haul destinations), keep a price history per route, and publish only fares that
are well below the route's own historical median. Every price we show is traceable to a stored
observation with its source and timestamp; nothing is estimated.

Our current source is a metasearch cache, which reaches us a median of 12.5 hours after a
traveller first saw the fare. We are looking for a licensed, live source, and Retailer PPS /
Infare appears to be the one product that covers the low-cost carriers that matter most to us
(Ryanair and Wizz Air are 43 % of our observations, then easyJet, TAP and Vueling).

**What we would like**

- Fare alerts (or a pull API) for the lowest round-trip fare per route and travel date, for the
  375 routes above, refreshed at least hourly.
- Fields: fare incl. taxes in EUR, outbound and return dates, carrier, nonstop or not, the
  selling channel the fare was collected from (airline site, OTA, GDS), and the collection time.
- **The right to publish the fare on our website**, in Portuguese, as "LIS–MXP 39 €, Ryanair,
  found at 14:02", with a link to the airline or an OTA that sells it. We would not redistribute
  the feed, expose it through an API or publish bulk data.
- A pilot (for example 3 months on a subset of routes) before any annual commitment.

**Questions**

1. Does Retailer PPS cover the carriers above from the six Portuguese airports, collected from the
   airlines' own websites? What is the actual refresh interval for routes of this size?
2. Is public display of individual fares (as described) within the licence, or does it need a
   separate rights clause? If so, what does it cost?
3. Delivery: webhook alerts, a REST pull API, or file drops? What is the typical latency between
   a fare appearing on the airline's site and its presence in your feed?
4. Price for the pilot and, indicatively, for a year at our volume. We are a small publisher, not
   an airline or OTA; if there is an entry-level tier or a startup programme, please point us to
   it.
5. Are historical fares (Altus) available for the same routes, to replace our own 2026 history
   for the "usual price" baseline?

Thank you,

[nome completo]
pontonomada.pt · [entidade] · [e-mail]

---

## 2. Skyscanner Data Products (Live Pricing Services)

**Subject:** Live Pricing Services for a Portuguese flight-deals site — terms for publishing
fares

Hello,

I run pontonomada.pt, a flight-deals website for travellers in Portugal. We follow the direct
routes from Lisbon, Porto, Faro, Madeira, Ponta Delgada and Terceira (375 routes plus about 20
long-haul destinations), keep a price history per route, and publish only fares well below the
route's historical median. Each published price points back to a stored observation with its
source and timestamp.

Your Travel API team told us earlier this month that price-only use is handled by Data Products,
so I am writing to ask about **Live Pricing Services** for this use.

**What we would like**

- Live (or near-live) lowest round-trip fares per route and travel date for the routes above,
  polled roughly every 30 minutes, with carrier, nonstop flag and the price in EUR.
- To publish the fare on our website in Portuguese with a booking link. Today our links go
  through an affiliate network; we need to know whether your terms require Skyscanner deep links
  and "Powered by Skyscanner" attribution for prices that come from your data, or whether the
  link may go to the airline or another seller.
- No redistribution: the data would be displayed on our pages only, never exposed through an API
  or sold on.

**Questions**

1. Is Live Pricing Services available to a publisher of our size, and what are the eligibility
   criteria? (We are below the Travel API's monthly-active-user thresholds.)
2. Which attribution and linking rules apply to prices from Live Pricing Services shown to the
   public? May they sit next to a non-Skyscanner booking link?
3. Freshness: how old can a price returned by the service be, and does it include Ryanair and
   Wizz Air fares from Portugal?
4. Pricing model (per query, per route, flat fee) and the minimum term. A short pilot would help
   us decide.
5. The Data Products Terms and Conditions page did not render for us; could you send the current
   terms as a document?

Thank you,

[nome completo]
pontonomada.pt · [entidade] · [e-mail]

---

## 3. Duffel sales (enterprise Order Form covering publication of selected fares)

**Subject:** Enterprise Order Form for publishing selected fares with a booking link (cl. 2.5(d),
2.5(a), 2.5(k))

Hello,

I run pontonomada.pt, a flight-deals website for travellers in Portugal. We track round-trip
fares on the direct routes from the six Portuguese airports (375 routes), keep a price history,
and publish a small number of fares per week that are well below each route's historical median,
with a link to book. Every published price is traceable to a stored observation.

We would like to use Duffel's live search for the airlines you connect directly from Portugal
(easyJet, Vueling, Transavia, TAP via Travelport, Volotea, Norwegian, Pegasus) in two ways:

1. **Verification**: when our existing data flags a candidate deal, run one offer request to
   confirm the fare is live before we publish it. Low volume: a few hundred searches a month.
2. **Monitoring** (if the terms and price allow): poll the cheapest fare on our routes every
   30 minutes. High volume: roughly 375 routes × several date windows × 48 polls a day.

I have read the Services Agreement and I understand that the standard terms do not allow this:
cl. 2.5(d) excludes metasearch use, 2.5(a) excludes republishing or displaying Supplier Data, and
2.5(k) requires the airline's prior written consent for marketing with its fares. I am therefore
asking whether an **enterprise Order Form** can name our use explicitly.

**What we would like the Order Form to cover**

- Publication, on our own website only, of selected fares found through Duffel, shown as price,
  dates, carrier and a booking link. No feed, API or bulk data to third parties.
- Whether the booking link may go to the airline's site, or must be a Duffel-powered checkout
  (we can build either; orders through Duffel would carry your per-order fee).
- Airline consent under cl. 2.5(k) for easyJet, Vueling, Transavia and TAP, and whether Duffel
  can obtain it on our behalf or we approach each airline ourselves.

**Questions**

1. Is such an Order Form something you sign with publishers of our size, and what does the
   enterprise pricing look like for the two volume profiles above (your public rate is 0.005 USD
   per search above a 1 500 : 1 search-to-order ratio)?
2. Which of the airlines above are on Direct Connect versus a GDS path, and does that change
   the consent needed?
3. Are Ryanair or Wizz Air on your roadmap? Without them a Duffel-only source covers about half
   of the fares our readers care about.
4. What does onboarding require (IATA accreditation, a merchant of record, KYC) for a Portuguese
   sole trader / small company?

Thank you,

[nome completo]
pontonomada.pt · [entidade] · [e-mail]

---

## What happens after the replies

- A "yes, with terms" from any vendor → a D-entry on the link rule (research §3, recommendation
  2: the link goes to the seller, Aviasales `price_now` as the automatic fallback) **before** a
  new `PriceSource` is written. The schema already keys observations by `source`.
- A quote → Miguel decides; the budget line and the D13 decision are his (research §5).
- No reply in two weeks → chase once through the same form, then treat that door as closed and
  record it in `2026-10-24-faster-deal-discovery.md` §2.6.
