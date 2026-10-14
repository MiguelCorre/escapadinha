// Fixture builds only: a placeholder OpenGraph image at the contract's path (see
// src/lib/fixture-images.ts). A build from real data emits nothing here.
import type { APIRoute, GetStaticPaths } from "astro";
import sharp from "sharp";
import data from "virtual:site-data";
import { fixtureImages, placeholderSvg, type FixtureImage } from "../../../../lib/fixture-images";

export const getStaticPaths = (() => fixtureImages(data)
  .filter((img) => img.ext === "jpg" && img.name === "og")
  .map((img) => ({ params: { id: img.id }, props: { img } }))) satisfies GetStaticPaths;

export const GET: APIRoute<{ img: FixtureImage }> = async ({ props }) => {
  const jpg = await sharp(Buffer.from(placeholderSvg(props.img))).jpeg({ quality: 70 }).toBuffer();
  return new Response(new Uint8Array(jpg), { headers: { "Content-Type": "image/jpeg" } });
};
