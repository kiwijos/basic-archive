/**
 * Builds an element. Children and text are added as text nodes, never as HTML, so nothing that
 * came from the archive (OCR text, titles, file names) can inject markup into the page.
 */
export function h(tag, props = {}, ...children) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (name.startsWith("on")) element.addEventListener(name.slice(2).toLowerCase(), value);
    else if (name === "class") element.className = value;
    else if (value === true) element.setAttribute(name, "");
    else element.setAttribute(name, String(value));
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return element;
}
