// Fixture builds only: placeholder slides and thumbnails at the contract's paths (see
// src/lib/fixture-images.ts). A build from real data emits nothing here.
import type { APIRoute, GetStaticPaths } from "astro";
import sharp from "sharp";
import data from "virtual:site-data";
import { fixtureImages, placeholderSvg, type FixtureImage } from "../../../../lib/fixture-images";

export const getStaticPaths = (() => fixtureImages(data)
  .filter((img) => img.ext === "webp")
  .map((img) => ({ params: { id: img.id, name: img.name }, props: { img } }))) satisfies GetStaticPaths;

export const GET: APIRoute<{ img: FixtureImage }> = async ({ props }) => {
  const webp = await sharp(Buffer.from(placeholderSvg(props.img))).webp({ quality: 60 }).toBuffer();
  return new Response(new Uint8Array(webp), { headers: { "Content-Type": "image/webp" } });
};
