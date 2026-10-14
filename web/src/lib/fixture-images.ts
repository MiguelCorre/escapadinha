// Stand-in images for a fixture build only (meta.fixture, D28): the contract's promotion image
// paths (/img/promos/<id>/thumb.webp, slide_NN.webp, og.jpg) are the pipeline's rendered files,
// which a fixture build doesn't have. Without them the pages' largest image 404s and Lighthouse
// never measures it, so a fixture build draws a placeholder at each path (the photo placeholder
// gradient, from the tokens, generated with sharp: no binary in the repository). A build from real
// data gets none of these routes: the cutover (#23) brings the real files.
import type { SiteData } from "./contract";
import { TOKENS } from "./tokens";

export interface FixtureImage {
  id: string;           // "3"
  name: string;         // "slide_01", "thumb", "og"
  ext: "webp" | "jpg";
  width: number;
  height: number;
}

const PATH = /^\/img\/promos\/(\d+)\/(thumb|slide_\d{2}|og)\.(webp|jpg)$/;
const SIZE: Record<string, [number, number]> = { thumb: [540, 675], slide: [1080, 1350], og: [1200, 630] };

/** Every image path the fixture promotions name; none unless the data is a fixture. */
export function fixtureImages(data: SiteData): FixtureImage[] {
  if (!data.meta.fixture) return [];
  const found = new Map<string, FixtureImage>();
  for (const p of data.promotions.promotions) {
    const img = p.images;
    for (const src of img ? [img.thumb, img.og, ...img.slides] : []) {
      const m = src ? PATH.exec(src) : null;
      if (!m) continue;
      const [width, height] = SIZE[m[2].startsWith("slide_") ? "slide" : m[2]];
      found.set(src!, { id: m[1], name: m[2], ext: m[3] as FixtureImage["ext"], width, height });
    }
  }
  return [...found.values()];
}

/** The placeholder's SVG: dark rule to photo scrim, like `.photo-placeholder`. */
export function placeholderSvg({ width, height }: Pick<FixtureImage, "width" | "height">): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">`
    + `<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">`
    + `<stop offset="0" stop-color="${TOKENS.themes.dark.rule}"/><stop offset="1" stop-color="${TOKENS.photo.scrim}"/>`
    + `</linearGradient></defs><rect width="100%" height="100%" fill="url(#g)"/></svg>`;
}
