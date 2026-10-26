import { expect, test } from "@playwright/test";

// Follows docs/demo.md click for click, with the labels the script uses, over HTTPS with the self-signed certificate. If a
// button is renamed, this fails, and so does the demo script it guards. It needs `make demo` data and says so when that is
// missing, rather than failing for a reason that is not the code's.
const token = process.env.STAFF_TOKEN;
const scan = process.env.SCAN_FILE;
const base = process.env.DEMO_URL ?? "https://localhost";
const word = `zebrafink${Array.from({ length: 6 }, () => "abcdefghijklmnopqrstuvwxyz"[Math.floor(Math.random() * 26)]).join("")}`;
const TILE = /\/iiif\/3\/[0-9a-f-]{36}\/\d+,\d+,\d+,\d+\/\d+,\d*\/0\/default\.jpg/;

test.use({ baseURL: base, ignoreHTTPSErrors: true });
test.describe.configure({ mode: "serial" });

let seeded = false;
test.beforeAll(async ({ playwright }) => {
  if (!token || !scan) throw new Error("Run through `make e2e`: STAFF_TOKEN and SCAN_FILE are required.");
  const api = await playwright.request.newContext({ baseURL: base, ignoreHTTPSErrors: true });
  const ships = await (await api.get("/api/search/subjects", { params: { q: "Nordstjarnan", kind: "ship" } })).json();
  seeded = ships.hits.some((hit) => hit.name === "Havsörnen");
  await api.dispose();
});

test("A3: a correction saved as verified is found in public search within seconds", async ({ page, browser, playwright }) => {
  await page.goto("/review");
  await page.getByLabel("Staff token").fill(token);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText(/Signed in as/)).toBeVisible();

  await page.getByRole("link", { name: "Upload", exact: true }).click();
  await page.getByLabel("Scan").setInputFiles(scan);
  await page.getByLabel("Title").fill("Demo letter");
  await page.getByLabel("Document type").fill("letter");
  await page.getByLabel("Date as written").fill("ca 1891");
  await page.getByRole("button", { name: "Upload" }).click();

  const text = page.getByLabel("Text on the page");
  await expect(page.getByRole("img", { name: /Scan of page 1/ })).toBeVisible();
  await expect.poll(async () => (await text.inputValue()).length, { timeout: 60_000, message: "the machine reading appears" }).toBeGreaterThan(20);
  await text.fill(`${await text.inputValue()} ${word}`);

  const started = Date.now();
  await page.getByRole("button", { name: "Save as verified" }).click();
  await expect(page.getByText("Saved. This page is now verified.")).toBeVisible();

  // What terminal B's timer does in the script: ask public search until the word is found as verified.
  const api = await playwright.request.newContext({ baseURL: base, ignoreHTTPSErrors: true });
  await expect
    .poll(async () => {
      const found = await (await api.get("/api/search/documents", { params: { q: word, _: String(Math.random()) } })).json();
      return found.hits[0]?.verified === true;
    }, { timeout: 30_000, intervals: [500] })
    .toBe(true);
  const seconds = (Date.now() - started) / 1000;
  expect(seconds, "'well under ten' seconds, as the script says").toBeLessThan(10);
  await api.dispose();

  const visitor = await (await browser.newContext({ ignoreHTTPSErrors: true, baseURL: base })).newPage();
  await visitor.goto("/");
  await visitor.getByLabel("Search the archive").fill(word);
  await visitor.getByRole("button", { name: "Search" }).click();
  const result = visitor.locator(".result").first();
  await expect(result.locator("mark").first()).toHaveText(word);
  await expect(result.getByText("Verified by a person")).toBeVisible();

  await page.getByText("History of this page's text").click();
  await expect(page.locator(".versions li")).toHaveCount(2);
  await expect(page.locator('.versions li[data-source="human"]')).toContainText("Corrected by");
  await expect(page.locator('.versions li[data-source="machine"]')).toContainText("tesseract");
  console.log(`A3: found as verified ${seconds.toFixed(1)} s after saving`);
});

test("A4: a misspelled name that the ship no longer has finds the ship, which is known by its latest", async ({ page }) => {
  test.skip(!seeded, "the demo data is not loaded: run `make demo`");
  await page.goto("/");
  await page.getByRole("button", { name: "Ships and organisations" }).click();
  await page.getByLabel("Search the archive").fill("Nordstjarnan");
  await page.getByRole("button", { name: "Search" }).click();

  const result = page.locator(".result").filter({ has: page.getByRole("link", { name: "Havsörnen" }) });
  await expect(result.locator(".matched-name")).toContainText('Matched the former name "Nordstjärnan"');
  await result.getByRole("link", { name: "Havsörnen" }).click();

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Havsörnen");
  await expect(page.locator(".names li")).toHaveCount(3);
  await expect(page.locator(".names li[data-matched]")).toContainText("Nordstjärnan");
  await expect(page.getByRole("link", { name: /Älvdrottningen/ }).first()).toBeVisible();

  await page.getByRole("link", { name: "← Back to your search" }).click();
  await expect(page.getByLabel("Search the archive")).toHaveValue("Nordstjarnan");

  for (const query of ["Havsornen", "Sofia"]) {
    await page.getByLabel("Search the archive").fill(query);
    await page.getByRole("button", { name: "Search" }).click();
    await expect(page.locator(".result").getByRole("link", { name: "Havsörnen" }).first()).toBeVisible();
  }
});

test("A5: the Chapman plate opens, zooming loads finer tiles that are all answered, and it has a second sheet", async ({ page }) => {
  test.skip(!seeded, "the demo data is not loaded: run `make demo`");
  const answers = [];
  page.on("requestfinished", async (request) => {
    if (TILE.test(request.url())) answers.push((await request.response()).status());
  });
  await page.goto("/");
  await page.getByLabel("Search the archive").fill("Hagbåt");
  await page.getByRole("button", { name: "Search" }).click();
  await page.locator(".result").getByRole("link", { name: /Hagbåt: planscherna VIII och IX/ }).click();

  await expect(page.locator(".viewer-stage canvas")).toBeVisible({ timeout: 30_000 });
  for (let step = 0; step < 6; step += 1) {
    await page.getByRole("button", { name: "Zoom in" }).click();
    await page.waitForTimeout(400);
  }
  await expect.poll(() => answers.length, { timeout: 20_000 }).toBeGreaterThan(10);
  await page.getByRole("button", { name: "Reset view" }).click();
  await page.getByRole("button", { name: "Page 2" }).click();
  await expect(page.getByRole("button", { name: "Page 2" })).toHaveAttribute("aria-pressed", "true");
  expect(answers.filter((status) => status !== 200), "every tile answered 200").toEqual([]);
});
