// The partner's search form loads lazily (D34): the page only carries the script's src in a data
// attribute; the loader adds the <script> when the box comes near the viewport (or, without
// IntersectionObserver, on the visitor's first interaction), once. Nothing is fetched before.
import { describe, expect, it } from "vitest";
import { mountSearchWidget, ROOT_MARGIN } from "../src/lib/search-widget";

const SRC = "https://tp.media/content?fake=test-only&promo_id=0";

interface FakeScript { tag: string; src?: string; async?: boolean; charset?: string }

function fakePage(withObserver = true) {
  const appended: FakeScript[] = [];
  const attrs = new Map<string, string>([["data-src", SRC]]);
  const listeners = new Map<string, () => void>();
  const observers: { callback: (entries: { isIntersecting: boolean }[]) => void; options: unknown;
    observed: unknown[]; disconnected: boolean }[] = [];
  const container = {
    getAttribute: (name: string) => attrs.get(name) ?? null,
    setAttribute: (name: string, value: string) => void attrs.set(name, value),
    appendChild: (node: FakeScript) => { appended.push(node); return node; },
  };
  class FakeObserver {
    entry: (typeof observers)[number];
    constructor(callback: (entries: { isIntersecting: boolean }[]) => void, options: unknown) {
      this.entry = { callback, options, observed: [], disconnected: false };
      observers.push(this.entry);
    }
    observe(el: unknown) { this.entry.observed.push(el); }
    disconnect() { this.entry.disconnected = true; }
  }
  const env = {
    document: { createElement: (tag: string): FakeScript => ({ tag }) },
    IntersectionObserver: withObserver ? FakeObserver : undefined,
    addEventListener: (type: string, fn: () => void) => void listeners.set(type, fn),
    removeEventListener: (type: string) => void listeners.delete(type),
  };
  return { container, env, appended, observers, listeners, attrs };
}

describe("search widget loader", () => {
  it("fetches nothing until the box comes near the viewport, then adds the script once", () => {
    const p = fakePage();
    mountSearchWidget(p.container as never, p.env as never);
    expect(p.appended).toEqual([]);
    expect(p.observers).toHaveLength(1);
    expect(p.observers[0].observed).toEqual([p.container]);
    expect(p.observers[0].options).toEqual({ rootMargin: ROOT_MARGIN });

    p.observers[0].callback([{ isIntersecting: false }]);
    expect(p.appended).toEqual([]);

    p.observers[0].callback([{ isIntersecting: true }]);
    expect(p.appended).toEqual([{ tag: "script", src: SRC, async: true, charset: "utf-8" }]);
    expect(p.observers[0].disconnected).toBe(true);
    expect(p.attrs.get("data-loaded")).toBe("true");

    p.observers[0].callback([{ isIntersecting: true }]);
    expect(p.appended).toHaveLength(1);
  });

  it("without IntersectionObserver, waits for the visitor's first interaction", () => {
    const p = fakePage(false);
    mountSearchWidget(p.container as never, p.env as never);
    expect(p.appended).toEqual([]);
    expect([...p.listeners.keys()].sort()).toEqual(["keydown", "pointerdown", "scroll"]);
    p.listeners.get("scroll")!();
    expect(p.appended.map((s) => s.src)).toEqual([SRC]);
    expect(p.listeners.size).toBe(0);
  });

  it("does nothing on a box without a script src", () => {
    const p = fakePage();
    p.attrs.delete("data-src");
    mountSearchWidget(p.container as never, p.env as never);
    expect(p.observers).toEqual([]);
    expect(p.appended).toEqual([]);
  });
});
