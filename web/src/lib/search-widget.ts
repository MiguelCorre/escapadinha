// Lazy loader for the partner's search form (D34). The page carries only the script's src (from
// Travelpayouts' widget constructor, config site.search_widget) in data-src on an empty box; the
// <script> is added inside that box when it comes within ROOT_MARGIN of the viewport, or, in a
// browser without IntersectionObserver, on the visitor's first scroll, tap or key press. Never
// before: the partner's script (and any cookie it sets) stays off a page nobody scrolls down.

export const ROOT_MARGIN = "300px 0px";
const INTERACTIONS = ["scroll", "pointerdown", "keydown"] as const;

interface LoaderEnv {
  document: Pick<Document, "createElement">;
  IntersectionObserver?: typeof IntersectionObserver;
  addEventListener: (type: string, fn: () => void, options?: AddEventListenerOptions) => void;
  removeEventListener: (type: string, fn: () => void) => void;
}

type Box = Pick<Element, "getAttribute" | "setAttribute" | "appendChild">;

export function mountSearchWidget(box: Box, env: LoaderEnv = window): void {
  const src = box.getAttribute("data-src");
  if (!src) return;
  let observer: IntersectionObserver | null = null;
  let loaded = false;
  const load = () => {
    if (loaded) return;
    loaded = true;
    observer?.disconnect();
    for (const type of INTERACTIONS) env.removeEventListener(type, load);
    const script = env.document.createElement("script");
    script.src = src;
    script.async = true;
    script.charset = "utf-8";
    box.appendChild(script);
    box.setAttribute("data-loaded", "true");
  };
  if (env.IntersectionObserver) {
    observer = new env.IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) load();
    }, { rootMargin: ROOT_MARGIN });
    observer.observe(box as Element);
  } else {
    for (const type of INTERACTIONS) env.addEventListener(type, load, { once: true, passive: true });
  }
}

/** Every search widget box on the page. */
export function mountSearchWidgets(doc: Document = document): void {
  doc.querySelectorAll("[data-search-widget]").forEach((box) => mountSearchWidget(box));
}
