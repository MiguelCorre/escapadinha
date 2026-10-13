# Launch checklist

The steps before the first public post, in order. Tick them as they're done.

## 1. Brand and channels
- [x] Brand name: **Ponto Nómada** (2026-10-13, D16). Logo still provisional; final logo once the domain is set.
- [x] Code ready for the switch (D17): `site.domain`, `site.legacy_hosts`, `_redirects`/`_headers`,
      per-channel `affiliate.projects`.
- [ ] Register `pontonomada.pt` (and `.com` as defensive), connect it to Cloudflare Pages, switch
      `site.base_url`, add the Bulk Redirect: **[docs/runbooks/brand-switch.md](docs/runbooks/brand-switch.md)**
      steps 1–6 (issue #22).
- [ ] Rename the Instagram handle to match, then a new Travelpayouts Project and `brand.handle`
      (runbook step 9).
- [x] Instagram account: https://www.instagram.com/ondestaanocas/ (handle may still change).
- [ ] Switch it to a **professional** (Business/Creator) account. v2 publishing via the Graph API needs this.
- [x] Website live at https://ondestaanocas.pages.dev (2026-10-13). Every scheduled run rebuilds it
      and deploys when the content changed.
- [ ] Put the site in the Instagram bio (https://pontonomada.pt once connected; until then
      https://ondestaanocas.pages.dev, which will redirect).
- [ ] Review the "Como funciona" and "Privacidade" texts (`src/escapadinha/website/templates/`).

## 2. Travelpayouts
- [x] Project for the Instagram profile: **ID 584711** "Instagram", Content creation, Portuguese (2026-10-12).
      Once a project is connected to programs its link **can't be edited**. If the handle changes,
      create a new project with the new URL and archive the old one.
- [ ] Create a separate Project for the website, **after** the domain is live (its URL is final
      once connected), and set `affiliate.projects.website` (runbook step 8).
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
