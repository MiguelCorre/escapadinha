// The price traceability checker (D2) shared by traceability.test.ts (the fixture build) and
// scale.test.ts (the synthetic build at full size). The rules are in traceability.test.ts.
import { parse, type HTMLElement } from "node-html-parser";
import type { SiteData } from "../src/lib/contract";

// "58 €", "85,40 €", "58€", "€58" with a normal or no-break space.
const PRICE = /(\d+(?:,\d{1,2})?)[  ]?€|€[  ]?(\d+(?:,\d{1,2})?)/g;
const REF_ATTRS = ["data-obs", "data-deal", "data-route"];
const cents = (value: number) => Math.round(value * 100);

export interface Amounts {
  obs: Map<number, Set<number>>;
  deal: Map<number, Set<number>>;
  route: Map<string, Set<number>>;
}

function add<K>(map: Map<K, Set<number>>, key: K, eur: number | null | undefined) {
  if (!map.has(key)) map.set(key, new Set());
  if (eur != null) map.get(key)!.add(cents(eur));
}

export function traceableAmounts(data: SiteData): Amounts {
  const a: Amounts = { obs: new Map(), deal: new Map(), route: new Map() };
  for (const p of data.promotions.promotions) {
    add(a.obs, p.offer.obs, p.offer.price);
    add(a.deal, p.id, p.offer.price);
    add(a.deal, p.id, p.typical_low);
    if (p.expired?.latest) {
      add(a.obs, p.expired.latest.obs, p.expired.latest.price);
      add(a.deal, p.id, p.expired.latest.price);
    }
  }
  for (const r of data.routes.routes) {
    add(a.route, r.key, null);
    for (const m of r.months) {
      add(a.route, r.key, m.typical_low);
      add(a.route, r.key, m.average);
    }
    if (r.cheapest) {
      add(a.route, r.key, r.cheapest.price);
      add(a.obs, r.cheapest.obs, r.cheapest.price);
    }
    for (const day of r.calendar) add(a.obs, day.obs, day.price);
  }
  for (const file of Object.values(data.lowPrices)) {
    for (const row of file.rows) add(a.obs, row[0], row[2]);
  }
  return a;
}

function nearestRefs(el: HTMLElement | null): HTMLElement | null {
  for (let e = el; e; e = e.parentNode as HTMLElement | null) {
    if (typeof e.hasAttribute === "function" && REF_ATTRS.some((attr) => e.hasAttribute(attr))) return e;
  }
  return null;
}

function allowed(refs: HTMLElement | null, amounts: Amounts): { ok: Set<number>; unknown: string[] } {
  const ok = new Set<number>();
  const unknown: string[] = [];
  if (!refs) return { ok, unknown };
  const take = <K>(map: Map<K, Set<number>>, attr: string, key: K) => {
    const set = map.get(key);
    if (!set) unknown.push(`${attr}="${key}"`);
    else set.forEach((c) => ok.add(c));
  };
  const obs = refs.getAttribute("data-obs");
  const deal = refs.getAttribute("data-deal");
  const route = refs.getAttribute("data-route");
  if (obs) take(amounts.obs, "data-obs", Number(obs));
  if (deal) take(amounts.deal, "data-deal", Number(deal));
  if (route) take(amounts.route, "data-route", route);
  return { ok, unknown };
}

/** Untraceable prices on one page: "<price> in <where>: <why>". */
export function untraceable(html: string, amounts: Amounts): { checked: number; problems: string[] } {
  const root = parse(html, { comment: false });
  const problems: string[] = [];
  let checked = 0;
  const check = (value: string, owner: HTMLElement, where: string) => {
    for (const m of value.matchAll(PRICE)) {
      checked += 1;
      const amount = cents(Number((m[1] ?? m[2]).replace(",", ".")));
      const refs = nearestRefs(owner);
      const { ok, unknown } = allowed(refs, amounts);
      if (!refs) problems.push(`${m[0]} in ${where}: no data-obs/data-deal/data-route around it`);
      else if (unknown.length) problems.push(`${m[0]} in ${where}: unknown ${unknown.join(", ")}`);
      else if (!ok.has(amount)) problems.push(`${m[0]} in ${where}: not an amount of ${refs.rawTagName} ${REF_ATTRS.filter((x) => refs.hasAttribute(x)).map((x) => `${x}="${refs.getAttribute(x)}"`).join(" ")}`);
    }
  };
  // A price may be split over elements ("86<span>&nbsp;€</span>"), so prices are matched in an
  // element's whole text; a match belongs to the deepest element whose text contains all of it.
  const walk = (el: HTMLElement) => {
    if (el.rawTagName === "script" || el.rawTagName === "style") return;
    for (const [name, value] of Object.entries(el.attributes ?? {})) check(value, el, `${name} of <${el.rawTagName}>`);
    const spans: { start: number; end: number; element: boolean }[] = [];
    let text = "";
    for (const child of el.childNodes) {
      const t = child.nodeType === 1 && ["script", "style"].includes((child as HTMLElement).rawTagName) ? "" : child.text;
      spans.push({ start: text.length, end: text.length + t.length, element: child.nodeType === 1 });
      text += t;
    }
    for (const m of text.matchAll(PRICE)) {
      const start = m.index!;
      const end = start + m[0].length;
      if (spans.some((s) => s.element && s.start <= start && end <= s.end)) continue; // a child's
      check(m[0], el, `text of <${el.rawTagName}>`);
    }
    for (const child of el.childNodes) if (child.nodeType === 1) walk(child as HTMLElement);
  };
  walk(root);
  return { checked, problems };
}
