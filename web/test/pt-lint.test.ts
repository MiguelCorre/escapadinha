// pt-PT lint (spec #1, story 50): the site's own copy, in the templates (src/**/*.astro) and the
// copy modules (src/lib/*.ts), must not use Brazilian Portuguese words or spellings, nor leave
// English UI text behind. Comments are skipped (they are written in English for developers).
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { MONTHS, MONTHS_SHORT, WEEKDAYS_SHORT } from "../src/lib/format";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";
import { builtPages, page } from "./html";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "../src");

/** Brazilian words and spellings -> the pt-PT word (case-insensitive, whole words). */
const BRAZILIAN: Record<string, string> = {
  "você": "tu", "ônibus": "autocarro", "trem": "comboio",
  "tela": "ecrã", "celular": "telemóvel", "café da manhã": "pequeno-almoço", "equipe": "equipa",
  "usuário": "utilizador", "usuários": "utilizadores", "contato": "contacto", "registro": "registo",
  "planejar": "planear", "planejamento": "planeamento", "esporte": "desporto", "banheiro": "casa de banho",
  "aeromoça": "assistente de bordo", "passagem aérea": "bilhete de avião", "passagens aéreas": "bilhetes de avião",
  "econômico": "económico", "econômica": "económica", "seção": "secção", "recepção": "receção",
  "geladeira": "frigorífico", "cardápio": "ementa", "metrô": "metro", "xícara": "chávena",
};

/** English UI leftovers (case-sensitive: code identifiers are lowercase or CamelCase). */
const ENGLISH = ["Buy", "Book", "Book now", "Search", "Price", "Prices", "Deal", "Deals", "Expired",
  "Home", "Flight", "Flights", "From", "Departure", "Return", "Details", "Read more", "Learn more",
  "Click here", "Loading", "Sign up", "Subscribe", "Share", "Next", "Previous"];

const WORD = "[\\p{L}\\p{N}_]";
const whole = (w: string, flags: string) =>
  new RegExp(`(?<!${WORD})${w.replace(/ /g, "\\s+")}(?!${WORD})`, flags);

function stripComments(source: string): string {
  return source
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
}

/** pt-PT problems in a template or module source: "<word>: <hint>". */
function ptViolations(source: string): string[] {
  const text = stripComments(source);
  const found: string[] = [];
  for (const [word, hint] of Object.entries(BRAZILIAN)) {
    if (whole(word, "iu").test(text)) found.push(`"${word}" (pt-BR): use "${hint}"`);
  }
  for (const word of ENGLISH) {
    if (whole(word, "u").test(text)) found.push(`"${word}" (English UI text)`);
  }
  return found;
}

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const path = join(dir, e.name);
    if (e.isDirectory()) return e.name === "data" ? [] : sources(path);
    return /\.(astro|ts)$/.test(e.name) && !e.name.endsWith(".d.ts") ? [path] : [];
  });
}

describe("pt-PT lint", () => {
  it("finds Brazilian and English words, ignoring comments and code", () => {
    expect(ptViolations("<p>Você pode reservar no celular.</p>")).toHaveLength(2);
    expect(ptViolations('<a class="btn">Book now</a>')).toEqual(['"Book" (English UI text)', '"Book now" (English UI text)']);
    expect(ptViolations("<!-- Book now --><p>Reserva já</p>\n// You can Buy here")).toEqual([]);
    expect(ptViolations('<PriceBlock view={view} /> <p class="text-price">Ver voo</p>')).toEqual([]);
  });

  it("passes over every template and copy module", () => {
    const files = sources(SRC);
    expect(files.some((f) => f.endsWith(".astro"))).toBe(true);
    const problems = files.flatMap((f) =>
      ptViolations(readFileSync(f, "utf8")).map((v) => `${relative(SRC, f)}: ${v}`));
    expect(problems).toEqual([]);
  });

  it("declares the document language as pt-PT on every built page", () => {
    expect(readFileSync(join(SRC, "layouts/Base.astro"), "utf8")).toContain('lang="pt-PT"');
    for (const path of builtPages()) {
      expect(page(path).querySelector("html")!.getAttribute("lang"), path).toBe("pt-PT");
    }
  });

  it("uses the same month and weekday words as the pipeline (labels.json)", () => {
    const { labels } = loadSiteData(FIXTURES_DIR);
    expect(MONTHS).toEqual(labels.months);
    expect(MONTHS_SHORT).toEqual(labels.months_short);
    expect(WEEKDAYS_SHORT).toEqual(labels.weekdays_short);
  });
});
