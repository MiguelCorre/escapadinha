# Launch checklist

The steps before the first public post, in order. Tick them as they're done.

## 1. Brand and channels
- [ ] Pick the real brand name and Instagram handle. "Escapadinha" is a placeholder, so check
      availability first.
- [ ] Create the Instagram account and switch it to a **professional** (Business/Creator) account.
      v2 publishing via the Graph API needs this.
- [ ] Put the website up (v3). Even a simple landing page works as a second traffic source and
      as the "link na bio".

## 2. Travelpayouts
- [ ] Create a **Project** for the Instagram profile (Profile → Projects → Create Project → paste its URL).
- [ ] Create a separate Project for the website.
- [ ] Generate tracked Aviasales links from the Project (link generator, later the Links API) and
      use them instead of the raw `aviasales.com/...&marker=789000` link in `meta.json`.
      Program terms 1.4 only allow network promo tools.
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
