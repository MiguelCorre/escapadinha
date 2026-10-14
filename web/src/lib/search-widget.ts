// Loader for the partner's search form (D34). The page carries only the script's src (from
// Travelpayouts' widget constructor, config site.search_widget) in data-src, and a button. The
// partner's <script> is added only when the visitor presses that button: nothing from the
// partner (script, request, cookie) reaches a page before that explicit action, which is what
// the privacy page promises. Scrolling, hovering or focusing loads nothing.

/** The button's text; the privacy page quotes it. */
export const SEARCH_BUTTON = "Pesquisar voos no Aviasales";
export const BUTTON = "[data-search-widget-load]";
export const SLOT = "[data-search-widget-slot]";

interface LoaderEnv {
  document: Pick<Document, "createElement">;
}

type Button = Pick<HTMLButtonElement, "addEventListener" | "hidden">;
type Slot = Pick<HTMLElement, "appendChild" | "setAttribute" | "focus">;
type Box = Pick<Element, "getAttribute" | "querySelector">;

export function mountSearchWidget(box: Box, env: LoaderEnv = window): void {
  const src = box.getAttribute("data-src");
  const button = box.querySelector(BUTTON) as Button | null;
  const slot = box.querySelector(SLOT) as Slot | null;
  if (!src || !button || !slot) return;
  let loaded = false;
  button.addEventListener("click", () => {
    if (loaded) return;
    loaded = true;
    const script = env.document.createElement("script");
    script.src = src;
    script.async = true;
    script.charset = "utf-8";
    slot.setAttribute("data-loaded", "true");
    slot.appendChild(script);
    button.hidden = true;
    slot.focus();             // keyboard users land where the form appears, not on <body>
  });
}

/** Every search widget box on the page. */
export function mountSearchWidgets(doc: Document = document): void {
  doc.querySelectorAll("[data-search-widget]").forEach((box) => mountSearchWidget(box));
}
