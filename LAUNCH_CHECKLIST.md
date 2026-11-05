# Launch checklist

The steps before the first public post, in order. Tick them as they're done.

## 1. Brand and channels
- [x] Brand name: **Ponto Nómada** (2026-10-13, D16). Logo still provisional; final logo once the domain is set.
- [x] Code ready for the switch (D19): `site.domain`, `site.legacy_hosts`, `_redirects`/`_headers`,
      per-channel `affiliate.projects`.
- [x] Register `pontonomada.pt` (and `.com` as defensive), connect it to Cloudflare Pages, switch
      `site.base_url`, add the Bulk Redirect: **[docs/runbooks/brand-switch.md](docs/runbooks/brand-switch.md)**
      steps 1–6 (issue #22, closed; `site.base_url` is https://pontonomada.pt since 2026-10-13).
- [x] Instagram account: https://www.instagram.com/ondestaanocas/ (the contact on the site's
      "Como funciona" and "Privacidade" pages).
- ~~Rename the Instagram handle, switch the account to professional, put the site in the bio~~:
      dropped 2026-11-05 (D57). Miguel closed the Instagram and Telegram tickets (#21, #24, #27,
      #50): the website is the product; nothing is posted on either channel.
- [x] Website live at https://ondestaanocas.pages.dev (2026-10-13). Every scheduled run rebuilds it
      and deploys when the content changed.
- [x] Cutover to the Astro site (`web/`, #23 phase 1, D35, 2026-10-14): `run`'s full path exports the
      data, builds `web/dist` and deploys it with the review Function; `_redirects` keeps every old
      URL. The first production deploy happens on the next full path after the merge (or
      `gh workflow run pipeline.yml -f full=true`).
- [x] First production deploy of the Astro site: 2026-10-14 (run 38595287906); the live crawl of the
      old sitemap gave 363/363 ok the same evening.
- [x] For a week after that first deploy (until 2026-10-21), daily: `uv run escapadinha site crawl
      --sitemap docs/cutover/jinja-sitemap-2026-10-14.xml` (the live Jinja sitemap saved before the
      cutover, 363 URLs) reports no broken URL. Done: 7 daily runs of the `crawl` workflow
      (2026-10-14 to 2026-10-20) and a local crawl on 2026-10-21, all 363/363 ok.
      Then the Jinja site was deleted (`SiteBuilder`, `website/templates/`, `site build-jinja`,
      the `crawl` workflow; #23 phase 2, 2026-10-21).
- [x] Review the "Como funciona" and "Privacidade" texts (`web/src/pages/sobre/`,
      `web/src/pages/privacidade/`). Done 2026-11-05 against the code: the airline's own fares
      (D47), the comparison prices (D48), the automatic approval (D46) and the airline links that
      bypass the affiliate; `web/test/seo.test.ts` pins the sentences.

## 2. Travelpayouts
- [x] Project for the Instagram profile: **ID 584711** "Instagram", Content creation, Portuguese (2026-10-12).
      Once a project is connected to programs its link **can't be edited**. If the handle changes,
      create a new project with the new URL and archive the old one.
- [x] Create a separate Project for the website, **after** the domain is live (its URL is final
      once connected), and set `affiliate.projects.website` (runbook step 8). Done 2026-10-13:
      Project "Pontonomada" **585209** for https://pontonomada.pt (Aviasales available at once).
- [x] Tracked Aviasales links come from the partner links API for Project 584711 (`affiliate_url` in
      `meta.json`, for example https://aviasales.tpo.lu/UQWMX2Ed). Program term 1.4 only allows network tools.
- [ ] **Set the payout method (Finance → Payout methods).** The condition was "both the website
      and the Instagram page up and running"; with Instagram dropped (2026-11-05, D57) the website
      alone counts, and it is up. Miguel's account: only he can do it.

## 3. Content
- [x] Review the tip `web/src/content/tips/voos-baratos.mdx` (add sources and `last_checked`),
      then set `reviewed: true` (its old `/guias/voos-baratos-dicas/` link then 301s to it). Approved by Miguel 2026-10-15.
- [ ] Replace the provisional logo (`assets/logo-light.svg`, `assets/logo-dark.svg`) with the
      designer's (M6); colours and type are the design system (`docs/design/design-system.md`).

## Rules to remember
- Never use paid search or media buying for Aviasales. Bookings from it aren't paid, and PPC with
  the brand name gets the account blacklisted.
- Every post keeps the "Publicidade · … links de afiliado …" disclosure.
