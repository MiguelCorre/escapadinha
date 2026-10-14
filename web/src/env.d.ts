/// <reference types="astro/client" />

declare module "virtual:site-data" {
  const data: import("./lib/contract").SiteData;
  export default data;
}

declare namespace App {
  interface Locals {
    /** The itinerary or tip being rendered, set by its page for the affiliate blocks (D37). */
    article?: import("./lib/affiliates").ArticleRef;
  }
}
