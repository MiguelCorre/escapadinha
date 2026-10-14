// The partner's search form loads only on an explicit action (D34): the page carries the script's
// src in a data attribute and a button; the loader adds the <script> when the button is pressed,
// once. Nothing is created, appended or fetched before: not on load, scroll, hover or focus.
import { describe, expect, it } from "vitest";
import { BUTTON, mountSearchWidget, SEARCH_BUTTON, SLOT } from "../src/lib/search-widget";

const SRC = "https://tp.media/content?fake=test-only&promo_id=0";

interface FakeScript { tag: string; src?: string; async?: boolean; charset?: string }

function fakePage() {
  const appended: FakeScript[] = [];
  const created: string[] = [];
  const attrs = new Map<string, string>([["data-src", SRC]]);
  const clicks: (() => void)[] = [];
  const otherListeners: string[] = [];
  let focused = false;
  const button = {
    hidden: false,
    addEventListener: (type: string, fn: () => void) => {
      if (type === "click") clicks.push(fn);
      else otherListeners.push(type);
    },
  };
  const slotAttrs = new Map<string, string>();
  const slot = {
    appendChild: (node: FakeScript) => { appended.push(node); return node; },
    setAttribute: (name: string, value: string) => void slotAttrs.set(name, value),
    focus: () => { focused = true; },
  };
  const box = {
    getAttribute: (name: string) => attrs.get(name) ?? null,
    querySelector: (selector: string) => (selector === BUTTON ? button : selector === SLOT ? slot : null),
  };
  const env = { document: { createElement: (tag: string): FakeScript => { created.push(tag); return { tag }; } } };
  const click = () => clicks.forEach((fn) => fn());
  return { box, button, env, appended, created, attrs, slotAttrs, clicks, otherListeners, click,
    focused: () => focused };
}

describe("search widget loader", () => {
  it("creates and requests nothing from the partner until the button is pressed", () => {
    const p = fakePage();
    mountSearchWidget(p.box as never, p.env as never);
    expect(p.created).toEqual([]);                  // no <script>, so no request to the partner
    expect(p.appended).toEqual([]);
    expect(p.clicks).toHaveLength(1);               // only a click listener: no scroll, hover...
    expect(p.otherListeners).toEqual([]);
    expect(p.button.hidden).toBe(false);
  });

  it("adds the partner's script once the button is pressed, and only once", () => {
    const p = fakePage();
    mountSearchWidget(p.box as never, p.env as never);
    p.click();
    expect(p.appended).toEqual([{ tag: "script", src: SRC, async: true, charset: "utf-8" }]);
    expect(p.slotAttrs.get("data-loaded")).toBe("true");
    expect(p.button.hidden).toBe(true);
    expect(p.focused()).toBe(true);                 // keyboard focus moves to the form's slot
    p.click();
    expect(p.appended).toHaveLength(1);
  });

  it("does nothing on a box without a script src or without its button", () => {
    const p = fakePage();
    p.attrs.delete("data-src");
    mountSearchWidget(p.box as never, p.env as never);
    expect(p.clicks).toEqual([]);
    const q = fakePage();
    q.box.querySelector = () => null;
    mountSearchWidget(q.box as never, q.env as never);
    expect(q.clicks).toEqual([]);
    expect(q.created).toEqual([]);
  });

  it("names the partner on the button the privacy page quotes", () => {
    expect(SEARCH_BUTTON).toBe("Pesquisar voos no Aviasales");
  });
});
