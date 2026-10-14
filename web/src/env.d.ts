/// <reference types="astro/client" />

declare module "virtual:site-data" {
  const data: import("./lib/contract").SiteData;
  export default data;
}
