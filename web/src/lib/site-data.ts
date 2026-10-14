// Load the website data contract (D27) from a directory and validate every file against the
// committed JSON Schemas. This is the web package's only input: a mismatch stops the build with
// the file and the field that broke, never a half-rendered site.
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { Ajv2020 } from "ajv/dist/2020.js";
import type { SiteData } from "./contract";

const WEB_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const CONTRACT_DIR = resolve(WEB_DIR, "../contract/site/v1");

/** Committed test data (meta.fixture: true): build and test from it, never deploy it. */
export const FIXTURES_DIR = join(CONTRACT_DIR, "fixtures");
/** Where the pipeline will export the data (config site.data_dir, from the cutover #23). */
export const DEFAULT_DATA_DIR = join(WEB_DIR, "src/data");

const SCHEMAS = ["defs", "meta", "labels", "origins", "routes", "destinations", "promotions",
  "low-prices"];
const ID = "https://pontonomada.pt/contract/site/v1/";

export class SiteDataError extends Error {}

/** SITE_DATA_DIR (relative to the web package), else web/src/data. */
export function dataDirFromEnv(env: Record<string, string | undefined> = process.env): string {
  return env.SITE_DATA_DIR ? resolve(WEB_DIR, env.SITE_DATA_DIR) : DEFAULT_DATA_DIR;
}

function validator() {
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  for (const name of SCHEMAS) {
    ajv.addSchema(JSON.parse(readFileSync(join(CONTRACT_DIR, `${name}.schema.json`), "utf8")));
  }
  return (schema: string, file: string, json: unknown): string[] => {
    const validate = ajv.getSchema(`${ID}${schema}.schema.json`)!;
    if (validate(json)) return [];
    return (validate.errors ?? []).map(
      (e) => `${file}: ${e.instancePath || "/"} ${e.message}${e.params ? ` ${JSON.stringify(e.params)}` : ""}`,
    );
  };
}

/** Read and validate every contract file in `dir`; throws SiteDataError listing all problems. */
export function loadSiteData(dir: string): SiteData {
  if (!existsSync(join(dir, "meta.json"))) {
    throw new SiteDataError(
      `No site data in ${dir} (meta.json missing). Export it with \`escapadinha export site-data\` ` +
      `or point SITE_DATA_DIR at a contract directory, e.g. \`npm run build:fixtures\`.`,
    );
  }
  const check = validator();
  const problems: string[] = [];
  const read = (file: string, schema: string): any => {
    const path = join(dir, file);
    if (!existsSync(path)) {
      problems.push(`${file}: missing`);
      return null;
    }
    let json: unknown;
    try {
      json = JSON.parse(readFileSync(path, "utf8"));
    } catch (err) {
      problems.push(`${file}: not JSON (${(err as Error).message})`);
      return null;
    }
    problems.push(...check(schema, file, json));
    return json;
  };

  const meta = read("meta.json", "meta");
  if (problems.length) throw report(dir, problems);
  const data = {
    meta,
    labels: read(meta.files.labels, "labels"),
    origins: read(meta.files.origins, "origins"),
    routes: read(meta.files.routes, "routes"),
    destinations: read(meta.files.destinations, "destinations"),
    promotions: read(meta.files.promotions, "promotions"),
    lowPrices: Object.fromEntries(
      Object.entries(meta.files.low_prices as Record<string, string>).map(
        ([origin, file]) => [origin, read(file, "low-prices")],
      ),
    ),
  };
  if (problems.length) throw report(dir, problems);
  return data as SiteData;
}

function report(dir: string, problems: string[]): SiteDataError {
  return new SiteDataError(
    `Site data in ${dir} does not match contract/site/v1:\n  ${problems.join("\n  ")}`,
  );
}
