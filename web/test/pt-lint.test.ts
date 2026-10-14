// pt-PT lint (spec #1, story 50): the site's own copy, in the templates (src/**/*.astro) and the
// copy modules (src/lib/*.ts), and the review Function's pages and messages (functions/**/*.ts,
// #9), must not use Brazilian Portuguese words or spellings, nor leave
// English UI text behind. Comments are skipped (they are written in English for developers).
// Itineraries and tips (MDX, #17) get the same lists plus number, date and no-price rules.
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { MONTHS, MONTHS_SHORT, WEEKDAYS_SHORT } from "../src/lib/format";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";
import { builtPages, page } from "./html";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "../src");
const FUNCTIONS = resolve(SRC, "../functions");

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

const CAPITAL_MONTHS = MONTHS.map((m) => m[0].toUpperCase() + m.slice(1));
const ENGLISH_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
  "September", "October", "November", "December"];

/** Content rules beyond the word lists: [pattern, problem]. */
const CONTENT_RULES: [RegExp, string][] = [
  [/€|(?<!\p{L})EUR(?!\p{L})|\d\s*euros?(?!\p{L})/iu,
    "no prices in content: link the official source, or show a contract price with its data-obs"],
  [/\d\.\d/u, 'numbers take a decimal comma and no dot ("3,5 km", "1200")'],
  [/(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)/u, 'write the date in words or as 06/11/2026 ("6 de novembro de 2026")'],
  [new RegExp(`\\d\\s+de\\s+(?:${CAPITAL_MONTHS.join("|")})(?!\\p{L})`, "u"), 'months are lowercase ("6 de novembro")'],
  [new RegExp(`(?<!\\p{L})(?:${ENGLISH_MONTHS.join("|")})(?!\\p{L})`, "u"), "English month name"],
  [/\d\s+%/u, 'no space before the percent sign ("20%")'],
  [/\d\s?(?:am|pm|a\.m\.|p\.m\.)(?!\p{L})/iu, 'use the 24-hour clock ("9:30", "21:00")'],
  [/(?<!\p{L})(?:estar|estou|estás|está|estamos|estão|estava|estavas|estávamos|estavam)\s+\p{L}+ndo(?!\p{L})/iu,
    'pt-BR gerund: use a + infinitive ("está a visitar")'],
];

/** The text an MDX file shows: front matter values (without YAML comments and the last-checked
 * date) and the body, links removed (URLs are not copy). */
function contentText(source: string): string {
  const front = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(source);
  const values = (front?.[1] ?? "").split(/\r?\n/)
    .filter((line) => !/^\s*#/.test(line) && !/^\s*last_checked\s*:/.test(line));
  const body = front ? source.slice(front[0].length) : source;
  return `${values.join("\n")}\n${body}`.replace(/https?:\/\/[^\s)>"']+/g, " ");
}

/** pt-PT problems in an itinerary or tip (MDX source): the word lists plus CONTENT_RULES. */
function contentViolations(source: string): string[] {
  const text = contentText(source);
  const rules = CONTENT_RULES.filter(([pattern]) => pattern.test(stripComments(text))).map(([, problem]) => problem);
  return [...ptViolations(text), ...rules];
}

function mdxFiles(dir: string): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const path = join(dir, e.name);
    return e.isDirectory() ? mdxFiles(path) : e.name.endsWith(".mdx") ? [path] : [];
  });
}

/** "<file>: <problem>" for every MDX file under the given folders. */
function lintContent(dirs: string[]): string[] {
  return dirs.flatMap((dir) => mdxFiles(dir).flatMap((f) =>
    contentViolations(readFileSync(f, "utf8")).map((v) => `${relative(dir, f).split(sep).join("/")}: ${v}`)));
}

describe("pt-PT lint", () => {
  it("finds Brazilian and English words, ignoring comments and code", () => {
    expect(ptViolations("<p>Você pode reservar no celular.</p>")).toHaveLength(2);
    expect(ptViolations('<a class="btn">Book now</a>')).toEqual(['"Book" (English UI text)', '"Book now" (English UI text)']);
    expect(ptViolations("<!-- Book now --><p>Reserva já</p>\n// You can Buy here")).toEqual([]);
    expect(ptViolations('<PriceBlock view={view} /> <p class="text-price">Ver voo</p>')).toEqual([]);
  });

  it("passes over every template and copy module", () => {
    const files = [...sources(SRC), ...sources(FUNCTIONS)];
    expect(files.some((f) => f.startsWith(FUNCTIONS))).toBe(true);
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

// Itineraries and tips (#17, D33): every MDX file, drafts and test-only content included, gets the
// same word lists plus the content rules: pt-PT number and date formats as src/lib/format.ts
// writes them, and no prices at all (prices come only from the data contract, with their
// observation: CLAUDE.md "never fabricate prices").
const CONTENT_DIRS = [join(SRC, "content"), resolve(SRC, "../test/fixtures/content")];

describe("pt-PT lint over itineraries and tips", () => {
  const mdx = (body: string, front = "title: Teste") => `---\n${front}\n---\n\n${body}\n`;

  it("fails on a seeded 'você', in the body or the front matter", () => {
    expect(contentViolations(mdx("Você vai gostar de Paris."))).toEqual(['"você" (pt-BR): use "tu"']);
    expect(contentViolations(mdx("Vais gostar.", "title: Você em Paris"))).toHaveLength(1);
    const dir = mkdtempSync(join(tmpdir(), "pn-content-"));
    try {
      writeFileSync(join(dir, "seeded.mdx"), mdx("Aqui você encontra o metro."), "utf8");
      expect(lintContent([dir])).toEqual(['seeded.mdx: "você" (pt-BR): use "tu"']);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("refuses prices: euro signs and amounts in euros", () => {
    for (const body of ["O bilhete custa 12 €.", "Paga 12,50 euros à entrada.", "Desde 30 EUR.", "Custa €15."]) {
      expect(contentViolations(mdx(body)), body).toEqual([expect.stringContaining("no prices in content")]);
    }
    expect(contentViolations(mdx("Confirma o preço no site oficial antes de ir."))).toEqual([]);
  });

  it("wants pt-PT numbers, dates and times", () => {
    expect(contentViolations(mdx("Fica a 3.5 km do centro."))).toEqual([expect.stringContaining("decimal comma")]);
    expect(contentViolations(mdx("Abre a 2026-11-06."))).toEqual([expect.stringContaining("date")]);
    expect(contentViolations(mdx("Fecha a 6 de Novembro."))).toEqual([expect.stringContaining("lowercase")]);
    expect(contentViolations(mdx("Open in November."))).toEqual([expect.stringContaining("English month")]);
    expect(contentViolations(mdx("Poupa 20 %."))).toEqual([expect.stringContaining('"20%"')]);
    expect(contentViolations(mdx("Abre às 9 am."))).toEqual([expect.stringContaining("24-hour")]);
    expect(contentViolations(mdx("Estou visitando o museu."))).toEqual([expect.stringContaining("a + infinitive")]);
    expect(contentViolations(mdx("Fica a 3,5 km; abre às 9:30 de 6 de novembro a 07/01/2027; poupa 20%.")))
      .toEqual([]);
  });

  it("ignores links, YAML comments and the last-checked date", () => {
    const front = "# Test-only: Book now\ntitle: Teste\nlast_checked: 2026-10-14\nsources:\n  - title: Fonte\n    url: https://example.com/a.b/2026-10-14?x=12.5";
    expect(contentViolations(mdx("Ver [a fonte](https://example.com/v1.2/precos).", front))).toEqual([]);
  });

  it("passes over every itinerary and tip", () => {
    const files = CONTENT_DIRS.flatMap(mdxFiles);
    expect(files.map((f) => f.split(/[\\/]/).pop())).toEqual(expect.arrayContaining(["voos-baratos.mdx", "paris-em-3-dias.mdx"]));
    expect(lintContent(CONTENT_DIRS)).toEqual([]);
  });
});
