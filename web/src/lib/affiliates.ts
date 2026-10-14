// Affiliate blocks in itineraries and tips (#18, D37): eSIM, travel insurance and activities.
// Authors place <EsimBlock />, <InsuranceBlock /> or <ActivitiesBlock /> in the MDX body and list
// the programme in the front matter (`affiliates:`); the pipeline creates the tracked link for the
// article (partner links API, website Project, sub_id per article) and exports it in
// affiliates.json. Which brand a programme is lives in config.yaml, never here: a block of a
// programme not configured (or still without a link) renders nothing and the build warns.
import type { Affiliates, Programme } from "./contract";

export const PROGRAMMES = ["esim", "insurance", "activities"] as const satisfies readonly Programme[];

export const BLOCK_REL = "sponsored nofollow noopener";

/** The article a block is rendered in, set by its page (Astro.locals, see env.d.ts). */
export interface ArticleRef {
  /** "<collection>/<entry id>": how affiliates.json names it. */
  key: string;
  /** The programmes its front matter lists. */
  affiliates: readonly string[];
}

/** Each block's pt-PT copy; the brand comes from the contract. */
export const BLOCK_COPY: Record<Programme, { title: string; text: (brand: string) => string; cta: (brand: string) => string }> = {
  esim: {
    title: "Internet no telemóvel",
    text: (brand) => `Com um eSIM da ${brand} tens dados móveis assim que aterras, sem trocar de cartão `
      + "nem pagar roaming. Instala-o antes de partir e confirma que o teu telemóvel é compatível.",
    cta: (brand) => `Ver eSIM da ${brand}`,
  },
  insurance: {
    title: "Seguro de viagem",
    text: (brand) => `Um seguro de viagem da ${brand} cobre despesas médicas, bagagem e cancelamentos. `
      + "Lê o que cada cobertura inclui antes de escolher.",
    cta: (brand) => `Ver seguros da ${brand}`,
  },
  activities: {
    title: "Bilhetes para museus e atrações",
    text: (brand) => `Reserva na ${brand} os bilhetes dos museus e atrações mais procurados e evita as filas `
      + "à entrada. Confirma horários e dias de fecho no site oficial.",
    cta: (brand) => `Ver atividades na ${brand}`,
  },
};

export interface Block {
  programme: Programme;
  title: string;
  text: string;
  href: string;
  cta: string;
  rel: string;
  disclosure: string;
}

/** A block, or why it renders nothing (for the build's warning). */
export type BlockResult = { block: Block } | { warning: string };

/**
 * The block of `programme` in `article`. Throws (the build stops) on an author's mistake: a block
 * outside an article, or of a programme its front matter does not list. A programme not
 * configured, or a link not created yet, is not a mistake: no block, and a warning.
 */
export function affiliateBlock(data: Affiliates, article: ArticleRef | undefined, programme: Programme): BlockResult {
  if (!article) throw new Error(`the ${programme} block can only be placed in an itinerary or a tip`);
  if (!article.affiliates.includes(programme)) {
    throw new Error(`${article.key}: the ${programme} block needs "${programme}" in the front matter's affiliates`);
  }
  const brand = data.programmes[programme]?.brand;
  if (!brand) {
    return { warning: `${article.key}: ${programme} block not shown: no programme configured (config.yaml affiliate.programmes.${programme})` };
  }
  const link = data.links.find((l) => l.article === article.key && l.programme === programme);
  if (!link) {
    return { warning: `${article.key}: ${programme} block not shown: no tracked link yet (the next export creates it)` };
  }
  if (!link.url.startsWith("https://")) throw new Error(`affiliate link is not https: ${link.url}`);
  const copy = BLOCK_COPY[programme];
  return {
    block: {
      programme, title: copy.title, text: copy.text(brand), href: link.url, cta: copy.cta(brand),
      rel: BLOCK_REL, disclosure: data.disclosure,
    },
  };
}
