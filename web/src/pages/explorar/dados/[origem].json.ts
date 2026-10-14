// One origin's low prices for the explorer island (D31), fetched only when a visitor picks
// that origin: the contract's rows as they are (each price next to its observation id, D2) plus
// the destination and airport names they need.
import type { APIRoute, GetStaticPaths } from "astro";
import data from "virtual:site-data";
import { originFile } from "../../../lib/explorer-data";

export const getStaticPaths = (() =>
  Object.keys(data.lowPrices).map((origem) => ({ params: { origem } }))) satisfies GetStaticPaths;

export const GET: APIRoute = ({ params }) =>
  new Response(JSON.stringify(originFile(data, params.origem!)), {
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
