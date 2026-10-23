import { expect, test } from "@playwright/test";

const token = process.env.STAFF_TOKEN;
const scan = process.env.SCAN_FILE;
const run = process.env.RUN_ID ?? String(Date.now());
const title = `Browser test ${run}`;
const corrected = "Skeppet Vega lämnade Göteborg den 14 mars 1891 med last av järn och trä.";

test.beforeAll(() => {
  if (!token || !scan) throw new Error("Run through `make e2e`: STAFF_TOKEN and SCAN_FILE are required.");
});

async function signIn(page) {
  await page.goto("/");
  await page.getByLabel("Staff token").fill(token);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText(/Signed in as/)).toBeVisible();
}

// The queue is paged, oldest first, so a new document is usually on the last page.
async function queueRow(page, documentTitle) {
  const row = page.locator(`tr:has(a:text-is("${documentTitle}"))`);
  const next = page.getByRole("button", { name: "Next" });
  for (let number = 1; ; number += 1) {
    await expect(page.locator("tbody tr, .empty:not([hidden])").first()).toBeVisible();
    if ((await row.count()) > 0) return row;
    if (!(await next.isVisible()) || (await next.isDisabled())) return undefined;
    await next.click();
    await expect(page.locator(".position")).toHaveText(`Page ${number + 1}`);
  }
}

test("a wrong token gets a clear message and no access", async ({ page }) => {
  await page.goto("/review");
  await page.getByLabel("Staff token").fill("not-a-real-token");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("token was not accepted");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Review queue" })).toHaveCount(0);
});

test("upload, wait for the text, correct it, and the document leaves the queue", async ({ page }) => {
  await signIn(page);

  await page.getByRole("link", { name: "Upload", exact: true }).click();
  await page.getByLabel("Scan").setInputFiles(scan);
  await page.getByLabel("Title").fill(title);
  await page.getByLabel("Document type").fill("letter");
  await page.getByLabel("Date as written").fill("ca 1891");
  await page.getByRole("button", { name: "Upload" }).click();

  // The review page: the scan is shown, and the machine's reading arrives without a reload.
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByRole("img", { name: /Scan of page 1/ })).toBeVisible();
  const text = page.getByLabel("Text on the page");
  await expect(text).toHaveValue(/Vega/, { timeout: 90_000 });
  await expect(page.locator(".page .badge").first()).toHaveAttribute("data-status", "ocr_done");

  // While it is unchecked the document is in the queue.
  await page.getByRole("link", { name: "← Review queue" }).click();
  const row = await queueRow(page, title);
  expect(row, "the document is in the review queue").toBeDefined();
  await expect(row).toContainText("0 of 1 image verified");
  await row.getByRole("link", { name: title }).click();

  await text.fill(corrected);
  await page.getByRole("button", { name: "Save as verified" }).click();
  await expect(page.getByText("Saved. This page is now verified.")).toBeVisible();
  await expect(page.locator(".page .badge").first()).toHaveAttribute("data-status", "verified");
  await expect(page.getByText(/has left the review queue/)).toBeVisible();

  // The earlier reading is kept in the history beside the correction.
  await page.getByText("History of this page's text").click();
  await expect(page.locator(".versions li")).toHaveCount(2);
  await expect(page.locator('.versions li[data-source="human"]')).toContainText("Corrected by");
  await expect(page.locator('.versions li[data-source="machine"]')).toContainText("tesseract");

  await page.getByRole("link", { name: "Back to the queue" }).click();
  await expect(page.getByRole("heading", { name: "Review queue" })).toBeVisible();
  expect(await queueRow(page, title), "a fully verified document has left the queue").toBeUndefined();

  // A reload on a deep address still lands on the same page, with the corrected text.
  await page.goBack();
  await page.reload();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByLabel("Text on the page")).toHaveValue(corrected);
});

test("a token refused mid-session returns to sign-in with a message, then back to the same page", async ({ page }) => {
  await signIn(page);
  await page.getByRole("link", { name: "Review queue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Review queue" })).toBeVisible();

  await page.evaluate(() => sessionStorage.setItem("archive.token", "revoked-token"));
  await page.reload();

  await expect(page.getByRole("alert")).toContainText("token was not accepted");
  await page.getByLabel("Staff token").fill(token);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/review$/);
  await expect(page.getByRole("heading", { name: "Review queue" })).toBeVisible();
});

test("an unknown address shows a page-not-found message after sign-in", async ({ page }) => {
  await signIn(page);
  await page.goto("/no/such/page");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
});
