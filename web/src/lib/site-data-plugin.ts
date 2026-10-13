// Vite plugin behind `import data from "virtual:site-data"`: loads SITE_DATA_DIR once per build,
// validates it against contract/site/v1 (site-data.ts) and hands the pages plain JSON.
import { join } from "node:path";
import type { Plugin } from "vite";
import { dataDirFromEnv, loadSiteData } from "./site-data";

const ID = "virtual:site-data";
const RESOLVED = "\0" + ID;

export function siteDataPlugin(): Plugin {
  return {
    name: "pontonomada:site-data",
    resolveId(id) {
      return id === ID ? RESOLVED : undefined;
    },
    load(id) {
      if (id !== RESOLVED) return undefined;
      const dir = dataDirFromEnv();
      this.addWatchFile(join(dir, "meta.json"));
      return `export default ${JSON.stringify(loadSiteData(dir))};`;
    },
  };
}
