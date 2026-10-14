// The explorer (/explorar/) and the ponte pages (/pontes/<ponte>/<origem>/) built from the
// committed fixtures (D31). Expected values read off the fixture JSON by hand: Lisboa has five
// low prices (Madeira 69/63/60 €, Barcelona 53/51 €), Porto one (Paris 70 €), Faro none; the
// fixtures list every ponte of 2026-2027, the upcoming ones (from the data's day, 14 October
// 2026) start with 1 December 2026, and no fixture trip fits any of them.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";
import { builtPages, distDir, page, pageSource, text } from "./html";

const SITE_DISCLOSURE = "Publicidade: os botões de reserva são links de afiliado.";
const PONTE = "/pontes/1-dezembro-2026/porto/";
const PAST = "/pontes/ano-novo-2026/lisboa/";
const data = loadSiteData(FIXTURES_DIR);
const upcoming = data.pontes.pontes.filter((p) => p.window.end >= "2026-10-14");

describe("explorer page", () => {
  const doc = () => page("/explorar/");

  it("server-renders Lisboa's destinations at their cheapest, by price, without JavaScript", () => {
    const items = doc().querySelectorAll("#explorer-results > li");
    expect(items.map((li) => li.getAttribute("data-route"))).toEqual(["LIS-BCN", "LIS-FNC"]);
    expect(text(items[0].querySelector('[data-obs="4667"]')!)).toBe("51 €");
    expect(text(items[1].querySelector('[data-obs="7222"]')!)).toBe("60 €");
    expect(text(items[1])).toContain("Mais 2 datas com preço baixo");
    expect(text(items[0])).toContain("Encontrado por um viajante a 13/10/2026");
    expect(text(doc().querySelector("#explorer-status")!))
      .toBe("Partida: Lisboa · 2 destinos, do mais barato para o mais caro.");
  });

  it("links every result to its tracked partner link, with the disclosure", () => {
    const links = doc().querySelectorAll('#explorer-results a[rel~="sponsored"]');
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "https://example.com/parceiro/site-low-4667", "https://example.com/parceiro/site-low-7222"]);
    expect(text(links[0].closest("[data-cta]")!)).toContain(SITE_DISCLOSURE);
  });

  it("has the filters for the island: origin, budget, month, nights, direct, weekend, ponte", () => {
    const form = doc().querySelector("form#explorer")!;
    expect(form.hasAttribute("hidden")).toBe(false);         // in place from the first paint
    expect(pageSource("/explorar/")).toContain("<noscript><style>#explorer{display:none}</style></noscript>");
    const names = form.querySelectorAll("[name]").map((e) => e.getAttribute("name"));
    expect(names).toEqual(["origem", "orcamento", "mes", "noites_min", "noites_max", "diretos",
      "fim_de_semana", "ponte"]);
    const origins = form.querySelectorAll("select[name=origem] option").map((o) => o.getAttribute("value"));
    expect(origins).toEqual(["LIS", "OPO", "FAO"]);
    const pontes = form.querySelectorAll("select[name=ponte] option").map((o) => o.getAttribute("value"));
    expect(pontes).toEqual(["", ...upcoming.map((p) => p.slug)]);
    expect(pontes[1]).toBe("1-dezembro-2026");                  // past ones are not offered
    expect(text(form.querySelector("[name=fim_de_semana]")!.parentNode!))
      .toBe("Só fins de semana (partida sexta ou sábado, regresso domingo ou segunda, até 3 noites)");
    const months = form.querySelectorAll("select[name=mes] option").map((o) => text(o));
    expect(months).toEqual(["Qualquer mês", "outubro de 2026", "novembro de 2026"]);
  });

  it("loads each origin's low prices lazily, from its own JSON file", () => {
    const html = pageSource("/explorar/");
    expect(html).not.toContain("site-low-3040");               // Porto's row: not in the page
    for (const [origin, file] of Object.entries(data.lowPrices)) {
      const json = JSON.parse(readFileSync(join(distDir(), "explorar", "dados", `${origin}.json`), "utf8"));
      expect(json.rows).toEqual(file.rows);
      expect(json.places.origin).toBe(origin);
    }
    const porto = JSON.parse(readFileSync(join(distDir(), "explorar", "dados", "OPO.json"), "utf8"));
    expect(porto.places.cities).toEqual({ PAR: "Paris" });
    expect(porto.places.airports).toEqual({ BVA: { name: "Beauvais", remote: true } });
    // Each result links to its route page (D30), at the path the contract gives.
    const opoPar = data.routes.routes.find((r) => r.key === "OPO-PAR")!;
    expect(porto.places.paths).toEqual({ PAR: opoPar.path });
  });

  it("draws a low price exactly like the route page does (one shared row, low-prices.ts)", () => {
    const explorer = doc().querySelector('#explorer-results li[data-obs="7222"]')!;
    const route = page("/voos/lisboa-madeira/").querySelector('[data-low-prices] li[data-obs="7222"]')!;
    const body = (li: typeof explorer) => li.childNodes
      .filter((n) => !["h3"].includes((n as typeof li).rawTagName) && !text(n as typeof li).startsWith("Mais "))
      .map((n) => text(n as typeof li)).join(" | ");
    expect(body(explorer)).toBe(body(route));
    expect(body(route)).toContain("Encontrado por um viajante a 13/10/2026 · visto por nós a");
    expect(body(route)).toContain("Ver voo e reservar →");
  });

  it("keeps the island small", () => {
    const scripts = doc().querySelectorAll("script[type=module]");
    const bytes = scripts.reduce((sum, s) => {
      const src = s.getAttribute("src");
      return sum + (src ? readFileSync(join(distDir(), src)).length : s.textContent.length);
    }, 0);
    expect(bytes).toBeGreaterThan(0);
    expect(bytes).toBeLessThan(10_000);
  });

  it("lists the upcoming pontes with a link per origin, titled in pt-PT", () => {
    const links = doc().querySelectorAll("#pontes a");
    expect(links.map((a) => a.getAttribute("href"))).toContain(PONTE);
    expect(links.map((a) => a.getAttribute("href"))).not.toContain(PAST);
    expect(links).toHaveLength(upcoming.length * data.origins.origins.length);
    const porto = links.find((a) => a.getAttribute("href") === PONTE)!;
    expect(porto.getAttribute("aria-label")).toBe("Ponte de 1 de dezembro desde o Porto");
  });

  it("is in the navigation and indexable", () => {
    expect(page("/").querySelector('nav a[href="/explorar/"]')).not.toBeNull();
    expect(doc().querySelector('meta[name="robots"]')).toBeNull();
  });
});

describe("ponte pages", () => {
  it("are built for every ponte and origin, past ones too, at the contract's paths", () => {
    const paths = data.pontes.pontes.flatMap((p) => p.origins.map((o) => o.path));
    expect(paths.length).toBeGreaterThan(upcoming.length * 3);
    expect(paths).toContain(PAST);
    for (const path of paths) expect(builtPages(), path).toContain(path);
  });

  it("say when a ponte has passed and stay out of search (no 404 for an indexed page)", () => {
    const doc = page(PAST);
    expect(text(doc.querySelector("h1")!)).toBe("Fim de semana de Ano Novo desde Lisboa");
    expect(text(doc.querySelector("[data-past]")!)).toContain("Esta ponte já passou.");
    expect(doc.querySelector('meta[name="robots"]')!.getAttribute("content")).toBe("noindex");
    expect(doc.querySelectorAll("#explorer-results > li")).toHaveLength(0);
    expect(page(PONTE).querySelector("[data-past]")).toBeNull();
  });

  it("explain the long weekend, cite the law and stay out of search when empty", () => {
    const doc = page(PONTE);
    expect(text(doc.querySelector("h1")!)).toBe("Ponte de 1 de dezembro desde o Porto");
    const body = text(doc.querySelector("main")!);
    expect(body).toContain("Restauração da Independência");
    expect(body).toContain("28 de novembro a 1 de dezembro");     // days off
    expect(body).toContain("segunda-feira, 30 de novembro");        // the bridge
    expect(body).toContain("partida a partir de 27 de novembro e regresso até 2 de dezembro");
    expect(body).toContain("Código do Trabalho");
    expect(doc.querySelector('meta[name="robots"]')!.getAttribute("content")).toBe("noindex");
    expect(doc.querySelectorAll("#explorer-results > li")).toHaveLength(0);
    expect(doc.querySelector('a[href="/explorar/"]')).not.toBeNull();
  });

  it("link the same ponte from the other origins", () => {
    const links = page(PONTE).querySelectorAll("[data-other-origins] a").map((a) => a.getAttribute("href"));
    expect(links).toEqual(["/pontes/1-dezembro-2026/lisboa/", "/pontes/1-dezembro-2026/faro/"]);
  });

  it("say when the holiday is optional (Carnaval)", () => {
    expect(text(page("/pontes/carnaval-2027/lisboa/").querySelector("main")!))
      .toContain("não é feriado obrigatório");
  });
});

describe("Lighthouse", () => {
  it("measures the explorer and a ponte page", () => {
    const config = JSON.parse(readFileSync(new URL("../lighthouserc.json", import.meta.url), "utf8"));
    const urls: string[] = config.ci.collect.url;
    expect(urls).toContain("http://localhost/explorar/");
    expect(urls).toContain(`http://localhost${PONTE}`);
  });
});
