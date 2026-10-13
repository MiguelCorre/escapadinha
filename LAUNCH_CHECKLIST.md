# Launch checklist

The steps before the first public post, in order. Tick them as they're done.

## 1. Brand and channels
- [x] Brand name: **Ponto Nómada** (2026-10-13, D16). Logo still provisional; final logo once the domain is set.
- [ ] Register `pontonomada.pt` (and `.com` as defensive) — guided in GitHub issue #22.
- [ ] Rename the Instagram handle to match (then: new Travelpayouts Project, update `brand.handle`).
- [x] Instagram account: https://www.instagram.com/ondestaanocas/ (handle may still change).
- [ ] Switch it to a **professional** (Business/Creator) account. v2 publishing via the Graph API needs this.
- [x] Website live at https://ondestaanocas.pages.dev (2026-10-13). Every scheduled run rebuilds it
      and deploys when the content changed.
- [ ] Put https://ondestaanocas.pages.dev in the Instagram bio.
- [ ] Review the "Como funciona" and "Privacidade" texts (`src/escapadinha/website/templates/`).

## 2. Travelpayouts
- [x] Project for the Instagram profile: **ID 584711** "Instagram", Content creation, Portuguese (2026-10-12).
      Once a project is connected to programs its link **can't be edited**. If the handle changes,
      create a new project with the new URL and archive the old one.
- [ ] Create a separate Project for the website.
- [x] Tracked Aviasales links come from the partner links API for Project 584711 (`affiliate_url` in
      `meta.json`, for example https://aviasales.tpo.lu/UQWMX2Ed). Program term 1.4 only allows network tools.
- [ ] **Set the payout method (Finance → Payout methods), only once BOTH the website and the
      Instagram page are up and running.**

## 3. Content
- [ ] Review `content/guides/voos-baratos-dicas.yaml`, then set `reviewed: true`.
- [ ] Replace placeholder branding: `assets/logo.svg`, colours in `renderer/templates/base.html.j2`,
      `brand` in `config.yaml`.

## Rules to remember
- Never use paid search or media buying for Aviasales. Bookings from it aren't paid, and PPC with
  the brand name gets the account blacklisted.
- Every post keeps the "Publicidade · … links de afiliado …" disclosure.
