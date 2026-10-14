// The components an itinerary or tip may use in its MDX body without importing them (D37): the
// pages pass this map to <Content components={...} />. An unknown tag stops the build.
import ActivitiesBlock from "./ActivitiesBlock.astro";
import EsimBlock from "./EsimBlock.astro";
import InsuranceBlock from "./InsuranceBlock.astro";

export const MDX_COMPONENTS = { EsimBlock, InsuranceBlock, ActivitiesBlock };
