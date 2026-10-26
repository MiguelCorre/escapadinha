# Kayak from Miguel's PC: one search, read like a person (2026-10-26)

*Exploration before D49 (the probe's second engine). One search on kayak.pt from this PC, in a
visible Chrome with a throwaway profile (scratchpad, deleted afterwards), consent declined, at
about 08:45–08:57 UTC, while the scheduled Google Flights probe was idle (never two browsers at
once). Three loads of the same results page and two clicks; nothing hidden, nothing retried.*

## What happened

- **No wall.** The home page shows a cookie dialog with a "Recusar tudo" button (the most
  privacy-preserving answer); after it, the search URL
  `https://www.kayak.pt/flights/OPO-FNC/2026-12-17/2026-12-21/1adults?sort=price_a&fs=stops=0`
  (one adult, cheapest first, nonstop filter) lands on results straight away. No "press and hold",
  no captcha, no 403 on the first plain visit or on the two later loads.
- **The list streams in** for about 10 s ("96 de 1733 voos" in the filter rail), 50 numbered
  cards (`[role=group][aria-label="Resultado número N"]`), pt-PT texts. A card's text is
  `6:30 – 8:30 | OPOAeroporto Francisco Sá Carneiro | - | FNCAeroporto da Madeira | direto |
  2h 00m | 21:20 – 23:25 | FNC… | - | OPO… | direto | 2h 05m | Ryanair | 0 | 0 | 44 € | Básica |
  Selecionar`; a mixed itinerary reads "easyJet, Ryanair" and "Light + Básica"; a leg with a stop
  reads "1 escala". Each leg has a checkbox labelled "Segmento 1: Ryanair, OPO 6:30 - FNC 8:30."
  (the airline and times per leg, machine-friendly), the bag icons "0 malas de mão permitidas,
  não incluídas no preço". The price is the cheapest booking site's for that itinerary. Sponsored
  cards ("Anúncio", eDreams, "Ver oferta") are not numbered results.
- **The sellers are not on the page.** Clicking a card expands it (flight numbers, aircraft,
  "11 ofertas desde 44 €", "Selecionar"); clicking "11 ofertas desde" opens nothing more. The
  "Selecionar" link (`/book/flight?…&bucket=ALL_OPTIONS`) redirected straight to ryanair.com's
  flight selection for those dates (one page view of the airline's site, by mistake: the
  exploration expected Kayak's own providers page). So reading the eleven sellers would cost a
  page on each seller's site, which is more volume on more sites for a comparison: not done.
- **Google Flights, the same trip, same morning:** "Google Flights via Ryanair 44–49 €" on the
  review pages. Kayak's 44 € agrees.

## What D49 builds from this

One page load per trip on Kayak: the cheapest nonstop card's price, the airlines named by the
segment labels, no seller (`gate` null): "Também visto · Kayak · 44 €". The wall detector knows
Kayak's "press and hold" check and a plain access-denied page. kayak.pt (pt-PT, euros) rather
than kayak.ie (English, euros): the comparison should be what a traveller in Portugal sees.
