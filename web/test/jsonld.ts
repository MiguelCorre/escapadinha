// JSON-LD validation (D34), the runtime half: one JSON Schema per schema.org type the site emits,
// checked with ajv on every block of every built page. Each schema lists exactly the schema.org
// properties we use (additionalProperties: false), so a misspelt or invented property fails
// here; their names and value types are the ones schema-dts (the pinned schema.org vocabulary,
// the compile-time half) accepts in src/lib/structured-data.ts. On top of the vocabulary they
// pin our own rules: https URLs on the site's base, ISO dates, EUR prices as numbers > 0.
import { Ajv2020 } from "ajv/dist/2020.js";
import type { HTMLElement } from "node-html-parser";

const BASE = "https://pontonomada.pt";
const SITE_URL = { type: "string", pattern: `^${BASE.replace(/\./g, "\\.")}/` };
const DAY = { type: "string", pattern: "^\\d{4}-\\d{2}-\\d{2}$" };
const CONTEXT = { const: "https://schema.org" };

const organization = {
  type: "object",
  additionalProperties: false,
  required: ["@type", "name", "url"],
  properties: {
    "@type": { const: "Organization" },
    name: { const: "Ponto Nómada" },
    url: { const: `${BASE}/` },
    sameAs: { type: "array", items: { type: "string", pattern: "^https://www\\.instagram\\.com/[A-Za-z0-9._]+/$" } },
  },
};

const airport = {
  type: "object",
  additionalProperties: false,
  required: ["@type", "iataCode", "name"],
  properties: {
    "@type": { const: "Airport" },
    iataCode: { type: "string", pattern: "^[A-Z0-9]{3}$" },
    name: { type: "string", minLength: 1 },
  },
};

const leg = {
  type: "object",
  additionalProperties: false,
  required: ["@type", "name", "departureTime", "tripOrigin", "itinerary"],
  properties: {
    "@type": { const: "Trip" },
    name: { enum: ["Ida", "Regresso"] },
    departureTime: DAY,
    tripOrigin: airport,
    itinerary: airport,
  },
};

const offer = {
  type: "object",
  additionalProperties: false,
  required: ["@type", "price", "priceCurrency", "url"],
  properties: {
    "@type": { const: "Offer" },
    price: { type: "number", exclusiveMinimum: 0 },
    priceCurrency: { const: "EUR" },
    url: SITE_URL,
  },
};

export const SCHEMAS: Record<string, object> = {
  WebSite: {
    type: "object",
    additionalProperties: false,
    required: ["@context", "@type", "name", "url", "inLanguage", "publisher"],
    properties: {
      "@context": CONTEXT,
      "@type": { const: "WebSite" },
      name: { const: "Ponto Nómada" },
      url: { const: `${BASE}/` },
      inLanguage: { const: "pt-PT" },
      publisher: organization,
    },
  },
  Organization: {
    ...organization,
    required: ["@context", ...organization.required],
    properties: { "@context": CONTEXT, ...organization.properties },
  },
  Trip: {
    type: "object",
    additionalProperties: false,
    required: ["@context", "@type", "name", "description", "url", "tripOrigin", "itinerary", "subTrip", "offers"],
    properties: {
      "@context": CONTEXT,
      "@type": { const: "Trip" },
      name: { type: "string", minLength: 1 },
      description: { type: "string", minLength: 1 },
      url: SITE_URL,
      tripOrigin: airport,
      itinerary: airport,
      subTrip: { type: "array", minItems: 2, maxItems: 2, items: leg },
      offers: offer,
    },
  },
  Article: {
    type: "object",
    additionalProperties: false,
    required: ["@context", "@type", "headline", "description", "inLanguage", "dateModified", "author",
      "publisher", "mainEntityOfPage", "url", "image"],
    properties: {
      "@context": CONTEXT,
      "@type": { const: "Article" },
      headline: { type: "string", minLength: 1, maxLength: 110 },
      description: { type: "string", minLength: 1 },
      inLanguage: { const: "pt-PT" },
      dateModified: DAY,
      author: organization,
      publisher: organization,
      mainEntityOfPage: SITE_URL,
      url: SITE_URL,
      image: SITE_URL,
    },
  },
  BreadcrumbList: {
    type: "object",
    additionalProperties: false,
    required: ["@context", "@type", "itemListElement"],
    properties: {
      "@context": CONTEXT,
      "@type": { const: "BreadcrumbList" },
      itemListElement: {
        type: "array",
        minItems: 2,
        items: {
          type: "object",
          additionalProperties: false,
          required: ["@type", "position", "name", "item"],
          properties: {
            "@type": { const: "ListItem" },
            position: { type: "integer", minimum: 1 },
            name: { type: "string", minLength: 1 },
            item: SITE_URL,
          },
        },
      },
    },
  },
};

const ajv = new Ajv2020({ allErrors: true, strict: true });
const validators = Object.fromEntries(Object.entries(SCHEMAS).map(([type, schema]) => [type, ajv.compile(schema)]));

export interface Block {
  type: string;
  data: Record<string, any>;
  el: HTMLElement;
}

/** The JSON-LD blocks of a parsed page. Throws on a block that is not JSON. */
export function jsonLd(doc: HTMLElement): Block[] {
  return doc.querySelectorAll('script[type="application/ld+json"]').map((el) => {
    const data = JSON.parse(el.textContent);
    return { type: data["@type"], data, el };
  });
}

/** Problems of one block: an unknown @type or the schema's errors. */
export function jsonLdErrors(block: Pick<Block, "type" | "data">): string[] {
  const validate = validators[block.type];
  if (!validate) return [`unknown @type ${JSON.stringify(block.type)}`];
  if (validate(block.data)) return [];
  return (validate.errors ?? []).map((e) => `${block.type}${e.instancePath} ${e.message} ${JSON.stringify(e.params)}`);
}
