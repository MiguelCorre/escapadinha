// The explorer's client island (D31): makes the filter form work (the page hides it when
// JavaScript is off, in <noscript>, so it takes its place from the first paint: no layout shift),
// loads the chosen origin's low prices on first use (/explorar/dados/<ORIGIN>.json, cached) and redraws
// the list with the same rules and HTML as the server (explorer.ts). Without JavaScript the
// page keeps its server-rendered default list.
import type { IslandConfig, OriginFile } from "./explorer-data";
import { NO_FILTERS, explore, resultsHtml, statusText, type Filters } from "./explorer";

function num(value: FormDataEntryValue | null): number | null {
  const n = Number(value);
  return value === null || value === "" || !Number.isFinite(n) || n <= 0 ? null : n;
}

function filtersOf(form: HTMLFormElement): Filters {
  const f = new FormData(form);
  return {
    ...NO_FILTERS,
    maxPrice: num(f.get("orcamento")),
    month: (f.get("mes") as string) || null,
    minNights: num(f.get("noites_min")),
    maxNights: num(f.get("noites_max")),
    directOnly: f.has("diretos"),
    weekendOnly: f.has("fim_de_semana"),
    ponte: (f.get("ponte") as string) || null,
  };
}

export function start(): void {
  const form = document.getElementById("explorer") as HTMLFormElement | null;
  const list = document.getElementById("explorer-results");
  const status = document.getElementById("explorer-status");
  const configEl = document.getElementById("explorer-config");
  if (!form || !list || !status || !configEl) return;
  const config = JSON.parse(configEl.textContent ?? "{}") as IslandConfig;
  const cache = new Map<string, Promise<OriginFile>>();
  const load = (iata: string): Promise<OriginFile> => {
    const origin = config.origins.find((o) => o.iata === iata)!;
    if (!cache.has(iata)) {
      cache.set(iata, fetch(origin.file).then((r) => {
        if (!r.ok) throw new Error(String(r.status));
        return r.json() as Promise<OriginFile>;
      }));
    }
    return cache.get(iata)!;
  };
  let latest = 0;

  const update = async () => {
    const mine = ++latest;
    const iata = new FormData(form).get("origem") as string;
    const name = config.origins.find((o) => o.iata === iata)?.name ?? iata;
    list.setAttribute("aria-busy", "true");
    try {
      const file = await load(iata);
      if (mine !== latest) return;
      const results = explore(file.rows, filtersOf(form), config.pontes);
      list.innerHTML = resultsHtml(results, file.places);
      status.textContent = statusText(results.length, name);
    } catch {
      if (mine !== latest) return;
      cache.delete(iata);
      status.textContent = "Não foi possível carregar os preços. Tenta outra vez dentro de momentos.";
    } finally {
      if (mine === latest) list.removeAttribute("aria-busy");
    }
  };

  form.addEventListener("input", update);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    update();
  });
  // A form the browser restored (back button) or changed before this ran: show what it says.
  const changed = JSON.stringify(filtersOf(form)) !== JSON.stringify(NO_FILTERS)
    || new FormData(form).get("origem") !== config.defaultOrigin;
  if (changed) update();
}
