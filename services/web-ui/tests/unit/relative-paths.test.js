import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

const ROOT = new URL("../../", import.meta.url).pathname;

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

const sources = [join(ROOT, "index.html"), ...files(join(ROOT, "src")).filter((f) => /\.(js|css|html)$/.test(f))];

// Links to the licences are the only addresses outside the archive the pages are allowed to name.
const ALLOWED_EXTERNAL = [/^https:\/\/creativecommons\.org\//];

test("no page names a host, so the UI works behind any Ingress host", () => {
  for (const file of sources) {
    for (const [address] of readFileSync(file, "utf8").matchAll(/(?:https?:)?\/\/[a-z0-9.-]+\.[a-z]{2,}[^\s"'`)]*|https?:\/\/[^\s"'`)]+/gi)) {
      assert.ok(ALLOWED_EXTERNAL.some((pattern) => pattern.test(address)), `${file} names ${address}`);
    }
    assert.doesNotMatch(readFileSync(file, "utf8"), /localhost|127\.0\.0\.1|location\.(origin|host|hostname)/, `${file} refers to a host`);
  }
});

test("what the pages fetch or link to starts at the root of the site or is built from a prefix, never from a scheme", () => {
  for (const file of sources.filter((f) => f.endsWith(".js"))) {
    const text = readFileSync(file, "utf8");
    assert.doesNotMatch(text, /fetch\(\s*["'`]https?:/, `${file} fetches an absolute address`);
    assert.doesNotMatch(text, /(?:href|src|action):\s*["'`](?!https:\/\/creativecommons\.org\/)https?:/, `${file} links to an absolute address`);
  }
});
