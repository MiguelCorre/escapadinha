# Launch checklist

The steps before the first public post, in order. Tick them as they're done.

## 1. Brand and channels
- [x] Brand name: **Ponto Nómada** (2026-10-13, D16). Logo still provisional; final logo once the domain is set.
- [x] Code ready for the switch (D19): `site.domain`, `site.legacy_hosts`, `_redirects`/`_headers`,
      per-channel `affiliate.projects`.
- [ ] Register `pontonomada.pt` (and `.com` as defensive), connect it to Cloudflare Pages, switch
      `site.base_url`, add the Bulk Redirect: **[docs/runbooks/brand-switch.md](docs/runbooks/brand-switch.md)**
      steps 1–6 (issue #22).
- [ ] Rename the Instagram handle to match, then a new Travelpayouts Project and `brand.handle`
      (runbook step 9, issue #27; keeping `@ondestaanocas` for now, decided 2026-10-14).
- [x] Instagram account: https://www.instagram.com/ondestaanocas/ (handle may still change).
- [ ] Switch it to a **professional** (Business/Creator) account. v2 publishing via the Graph API needs this.
- [x] Website live at https://ondestaanocas.pages.dev (2026-10-13). Every scheduled run rebuilds it
      and deploys when the content changed.
- [x] Cutover to the Astro site (`web/`, #23 phase 1, D35, 2026-10-14): `run`'s full path exports the
      data, builds `web/dist` and deploys it with the review Function; `_redirects` keeps every old
      URL. The first production deploy happens on the next full path after the merge (or
      `gh workflow run pipeline.yml -f full=true`).
- [x] First production deploy of the Astro site: 2026-10-14 (run 38595287906); the live crawl of the
      old sitemap gave 363/363 ok the same evening.
- [ ] For a week after that first deploy (until 2026-10-21), daily: `uv run escapadinha site crawl
      --sitemap docs/cutover/jinja-sitemap-2026-10-14.xml` (the live Jinja sitemap saved before the
      cutover, 363 URLs) reports no broken URL. `.github/workflows/crawl.yml` runs it every day at
      07:30 UTC; a red run e-mails the owner.
      Then delete the Jinja site (`SiteBuilder`, `website/templates/`, `site build-jinja`; #23 phase 2).
- [ ] Put the site in the Instagram bio (https://pontonomada.pt once connected; until then
      https://ondestaanocas.pages.dev, which will redirect).
- [ ] Review the "Como funciona" and "Privacidade" texts (`web/src/pages/sobre/`,
      `web/src/pages/privacidade/`).

## 2. Travelpayouts
- [x] Project for the Instagram profile: **ID 584711** "Instagram", Content creation, Portuguese (2026-10-12).
      Once a project is connected to programs its link **can't be edited**. If the handle changes,
      create a new project with the new URL and archive the old one.
- [x] Create a separate Project for the website, **after** the domain is live (its URL is final
      once connected), and set `affiliate.projects.website` (runbook step 8). Done 2026-10-13:
      Project "Pontonomada" **585209** for https://pontonomada.pt (Aviasales available at once).
- [x] Tracked Aviasales links come from the partner links API for Project 584711 (`affiliate_url` in
      `meta.json`, for example https://aviasales.tpo.lu/UQWMX2Ed). Program term 1.4 only allows network tools.
- [ ] **Set the payout method (Finance → Payout methods), only once BOTH the website and the
      Instagram page are up and running.**

## 3. Content
- [ ] Review the tip `web/src/content/tips/voos-baratos.mdx` (add sources and `last_checked`),
      then set `reviewed: true` (its old `/guias/voos-baratos-dicas/` link then 301s to it).
- [ ] Replace the provisional logo (`assets/logo-light.svg`, `assets/logo-dark.svg`) with the
      designer's (M6); colours and type are the design system (`docs/design/design-system.md`).

## Rules to remember
- Never use paid search or media buying for Aviasales. Bookings from it aren't paid, and PPC with
  the brand name gets the account blacklisted.
- Every post keeps the "Publicidade · … links de afiliado …" disclosure.
