import { badgeFor } from "./badges.js";
import { h } from "./dom.js";

/** A Review status shown as a badge: its label in words, its code kept for styling and tests. */
export function badge(status, count) {
  const { label, tone } = badgeFor(status);
  return h(
    "span",
    { class: `badge badge-${tone}`, "data-status": status },
    label,
    count === undefined ? null : h("span", { class: "badge-count" }, ` ${count}`),
  );
}

/** A "Page 2" style link that moves within the app without reloading, and still works as a normal link. */
export function link(navigate, path, text) {
  return h(
    "a",
    {
      href: path,
      onclick: (event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
        event.preventDefault();
        navigate(path);
      },
    },
    text,
  );
}

export function formatTime(iso) {
  return new Date(iso).toLocaleString("sv-SE", { dateStyle: "short", timeStyle: "short" });
}

/** Text with its matches marked, built from parts so nothing from the archive is ever read as HTML. */
export function highlighted(parts) {
  return parts.map((part) => (part.match ? h("mark", {}, part.text) : part.text));
}

/** How far a text can be trusted: always in words, never by colour alone. */
export function verificationBadge({ status, label }) {
  return h("span", { class: `badge badge-verification badge-${status}`, "data-verification": status }, label);
}
