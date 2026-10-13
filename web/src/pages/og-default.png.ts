// The branded default OpenGraph image (1200×630) for pages without their own: the logo on paper
// with the masthead's double rule, rendered at build time from assets/logo-light.svg (its wordmark
// is outlined to paths, so no font is needed). Promotion pages use their rendered og.jpg instead.
import type { APIRoute } from "astro";
import sharp from "sharp";
import logo from "../../../assets/logo-light.svg?raw";

const W = 1200;
const H = 630;

export const GET: APIRoute = async () => {
  const inner = logo
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/<title>[\s\S]*?<\/title>/, "")
    .replace(/^[\s\S]*?<svg[^>]*>/, "")
    .replace(/<\/svg>\s*$/, "");
  const scale = 2.2; // logo viewBox is 418×60
  const x = (W - 418 * scale) / 2;
  const y = (H - 60 * scale) / 2 - 30;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
    <rect width="${W}" height="${H}" fill="#F5F0E6"/>
    <g transform="translate(${x} ${y}) scale(${scale})">${inner}</g>
    <rect x="${x}" y="${y + 60 * scale + 40}" width="${418 * scale}" height="3" fill="#1E1B16"/>
    <rect x="${x}" y="${y + 60 * scale + 49}" width="${418 * scale}" height="3" fill="#1E1B16"/>
  </svg>`;
  const png = await sharp(Buffer.from(svg)).png().toBuffer();
  return new Response(new Uint8Array(png), { headers: { "Content-Type": "image/png" } });
};
