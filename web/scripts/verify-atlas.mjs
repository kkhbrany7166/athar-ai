/** Explicit opt-in live browser smoke test. Never run by npm test. */
import { chromium, expect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
if (process.env.ATHAR_LIVE_DEMO !== "1")
  throw new Error(
    "Set ATHAR_LIVE_DEMO=1 to authorize live, billable Atlas processing and search.",
  );
const output = new URL(
  "../../data/processed/web-verification/",
  import.meta.url,
);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(15000);
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
try {
  await page.goto("http://localhost:3000");
  const load = page
    .getByRole("complementary", { name: "Workspace navigation" })
    .getByRole("button", { name: "Load Project Atlas ↗" });
  await expect(load).toBeEnabled();
  const loadedResponse = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/projects/atlas/load") &&
      r.request().method() === "POST",
  );
  await load.click();
  const project = await (await loadedResponse).json();
  console.log("Atlas workspace created:", project.id);
  await expect(page.getByRole("status")).toContainText(
    "Building project memory",
  );
  await page.screenshot({
    path: new URL("processing.png", output).pathname,
    fullPage: true,
  });
  await expect(
    page.getByRole("heading", { name: "Project decisions", exact: true }),
  ).toBeVisible({ timeout: 300000 });
  await expect(page.locator(".record")).toHaveCount(2);
  await expect(
    page.getByRole("region", { name: "Decision timeline" }),
  ).toContainText("12 Aug 2026");
  await expect(
    page.getByRole("region", { name: "Decision timeline" }),
  ).toContainText("3 Sept 2026");
  console.log("Live processing ready; both decision dates visible.");
  await page.screenshot({
    path: new URL("decisions.png", output).pathname,
    fullPage: true,
  });
  const receivedSearch = page.waitForResponse(
    (r) => r.url().endsWith("/api/search") && r.request().method() === "POST",
    { timeout: 180000 },
  );
  await page
    .getByRole("button", {
      name: "Why did the team replace Falcon Systems?",
      exact: true,
    })
    .click();
  const search = await (await receivedSearch).json();
  await expect(
    page.getByRole("heading", { name: "Retrieved evidence", exact: true }),
  ).toBeVisible();
  const top = search.results[0].result;
  expect(top.result_type).toBe("decision");
  expect(
    top.evidence_references.some((ref) => ref.source === "meeting_03_ar.md"),
  ).toBe(true);
  const evidence = page.getByRole("complementary", { name: "Source evidence" });
  const quotes = await evidence.locator("blockquote").allTextContents();
  expect(quotes).toEqual(top.evidence_references.map((ref) => ref.excerpt));
  await page.screenshot({
    path: new URL("search-evidence.png", output).pathname,
    fullPage: true,
  });
  console.log(
    "Replacement decision is top result; UI excerpts exactly equal backend excerpts.",
  );
  await page.getByRole("button", { name: "Open Loops", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "No unresolved commitments found" }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Completed 1" }).click();
  const historyResponse = page.waitForResponse((r) =>
    /\/api\/actions\/[^/?]+\?/.test(r.url()),
  );
  await page.getByRole("button", { name: /View commitment history/ }).click();
  const action = await (await historyResponse).json();
  expect(action.state).toBe("completed");
  expect(action.history[0].event_id).toBe(action.action.id);
  expect(action.history.map((event) => event.event_type)).toEqual([
    "assignment",
    "completed",
  ]);
  await expect(
    page.getByRole("heading", { name: "Commitment history" }),
  ).toBeVisible();
  await expect(page.locator(".history")).toContainText("Original assignment");
  await expect(page.locator(".history")).toContainText("7 Sept 2026");
  await page.screenshot({
    path: new URL("action-history.png", output).pathname,
    fullPage: true,
  });
  console.log(
    "Ahmed completed; assignment and completion preserve the same action identity.",
  );
  await page.getByRole("button", { name: "Documents", exact: true }).click();
  await expect(page.locator(".document-row")).toHaveCount(3);
  await expect(page.locator(".document-row .badge")).toHaveText([
    "Ready",
    "Ready",
    "Ready",
  ]);
  await page.screenshot({
    path: new URL("documents.png", output).pathname,
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Decisions", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Retrieved evidence", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: new URL("mobile.png", output).pathname,
    fullPage: true,
  });
  expect(errors).toEqual([]);
  await writeFile(
    new URL("live-report.json", output),
    JSON.stringify(
      {
        project_id: project.id,
        search,
        action,
        checks: [
          "three ready documents",
          "verified decision dates",
          "replacement top-1",
          "exact UI evidence",
          "same-ID action completion",
          "mobile no overflow",
          "no browser exceptions",
        ],
      },
      null,
      2,
    ),
  );
  console.log(
    "Browser verification passed. Screenshots and report:",
    output.pathname,
  );
} finally {
  await browser.close();
}
