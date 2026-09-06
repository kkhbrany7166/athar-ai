import { test, expect, type Page } from "@playwright/test";
import type { Action, Project } from "../lib/types";
const id = "offline-project";
const quote = "أكد أحمد: Nova API جاهز.\nناقش الفريق Falcon Systems.\n<script>not executable</script>";
const ref = {
  source: "meeting_ar.md",
  page: 2,
  excerpt: quote,
  document_id: "document-1",
  chunk_id: "chunk-1",
};
const decision = {
  decision_id: "decision-1",
  title: "تغيير المورد إلى Nova",
  description: "قرار موثق",
  rationale: "Delivery schedule",
  date: null,
  date_status: "unknown",
  evidence_references: [ref],
};
const original = {
  id: "action-1",
  description: "أحمد to obtain Nova plan",
  owner: "أحمد",
  deadline_text: "قبل يوم الأحد",
  evidence_references: [ref],
};
const action: Action = {
  action: original,
  owner: "أحمد",
  state: "completed",
  unresolved: false,
  assignment_date: "2026-09-03",
  latest_known_date: "2026-09-07",
  warnings: [],
  history: [
    {
      event_id: "action-1",
      event_type: "assignment",
      date: "2026-09-03",
      description: "Original assignment",
      applied: true,
      evidence_references: [ref],
    },
    {
      event_id: "event-1",
      event_type: "completed",
      date: "2026-09-07",
      description: "Plan received",
      applied: true,
      evidence_references: [ref],
    },
  ],
};
const project: Project = {
  id,
  name: "Offline UI fixture",
  synthetic: true,
  status: "ready",
  stage: "Ready",
  error: null,
  documents: [],
  snapshot_id: "snapshot-1",
};
async function mockAPI(
  page: Page,
  options: {
    failed?: boolean;
    upload?: boolean;
    slowSearch?: boolean;
    summary?: boolean;
    risks?: boolean;
    timeline?: boolean;
  } = {},
) {
  let current = structuredClone(project);
  let releaseSearch: (() => void) | undefined;
  await page.route("http://localhost:8000/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown;
    if (options.failed) {
      await route.fulfill({
        status: 503,
        json: { detail: "Local API temporarily unavailable." },
      });
      return;
    }
    if (path === "/api/health") body = { status: "ok", ai_configured: true };
    else if (path === "/api/projects") body = [current];
    else if (path === `/api/projects/${id}`) body = current;
    else if (path === "/api/decisions")
      body = {
        timeline: options.timeline
          ? [
              {
                ...decision,
                decision_id: "english-decision",
                title: "Select Falcon Systems",
                date: "2026-08-12",
                date_status: "verified",
              },
              decision,
            ]
          : [decision],
        risks: options.risks
          ? [
              {
                id: "risk-1",
                description: "تأخر Falcon API",
                severity: "unknown",
                status: "open",
                evidence_references: [ref],
              },
              {
                id: "risk-2",
                description: "No metadata supplied",
                evidence_references: [ref],
              },
            ]
          : [],
        rejected_records: 1,
      };
    else if (path === "/api/actions") body = [action];
    else if (path === "/api/actions/action-1") body = action;
    else if (path === "/api/search") {
      if (options.slowSearch)
        await new Promise<void>((resolve) => {
          releaseSearch = resolve;
        });
      body = {
        results: options.summary
          ? [
              {
                candidate_id: "c1",
                base_rank: 2,
                reranked_rank: 1,
                base_score: 0.7,
                relevance: 4,
                result: {
                  result_type: "decision",
                  item_id: "decision-1",
                  text: decision.description,
                  cosine_score: 0.7,
                  item: { id: "decision-1", ...decision },
                  evidence_references: [ref],
                },
              },
              {
                candidate_id: "c2",
                base_rank: 1,
                reranked_rank: 2,
                base_score: 0.8,
                relevance: 2,
                result: {
                  result_type: "document",
                  item_id: null,
                  text: quote,
                  cosine_score: 0.8,
                  item: null,
                  evidence_references: [ref],
                },
              },
            ]
          : [],
        timeline: options.summary
          ? [{ ...decision, date: "2026-09-03", date_status: "verified" }]
          : [],
        rerank_status: "applied",
        rerank_model_calls: 1,
      };
    } else if (path === "/api/documents/upload" && options.upload) {
      current = {
        ...current,
        status: "uploaded",
        documents: [
          {
            id: "file-1",
            filename: "notes.md",
            size: 12,
            status: "uploaded",
            kind: "document",
          },
        ],
      };
      body = current;
    } else if (path === "/api/process" && options.upload) {
      body = { ...current, status: "processing", stage: "Reading evidence…" };
      current = {
        ...current,
        status: "failed",
        error:
          "Processing could not finish. Check readable text and API access.",
        documents: current.documents.map((d) => ({ ...d, status: "failed" })),
      };
    } else {
      await route.fulfill({
        status: 404,
        json: { detail: "Offline test blocked an unexpected endpoint." },
      });
      return;
    }
    await route.fulfill({ json: body });
  });
  return () => releaseSearch?.();
}

test("unknown dates and exact bilingual evidence are rendered as text", async ({
  page,
}) => {
  await mockAPI(page);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: decision.title }),
  ).toBeVisible();
  await expect(page.locator(".record-meta")).toContainText("Unknown date");
  await expect(page.locator(".notice")).toContainText(
    "1 proposed record(s) were omitted",
  );
  await page
    .locator(".record")
    .getByRole("button", { name: "Inspect evidence ↗" })
    .click();
  const panel = page.getByRole("complementary", { name: "Source evidence" });
  expect(await panel.locator("blockquote").textContent()).toBe(quote);
  await expect(panel.locator("blockquote .mixed-latin").filter({ hasText: "Falcon Systems." })).toHaveText("Falcon Systems.");
  await expect(panel.locator("blockquote")).toHaveAttribute("dir", "auto");
  await expect(panel.locator("script")).toHaveCount(0);
  await expect(panel).toContainText("Page 2");
});

test("completed commitment history is separate and keyboard tabs work", async ({
  page,
}) => {
  await mockAPI(page);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: decision.title }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Open Loops", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "No unresolved commitments found" }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Open loops 0" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Completed 1" })).toBeFocused();
  await page.locator(".action-row").click();
  await expect(page.locator(".history")).toContainText("3 Sept 2026");
  await expect(page.locator(".history")).toContainText("7 Sept 2026");
  await page.getByText("Commitment identity", { exact: true }).click();
  await expect(page.locator(".action-history .technical")).toHaveText(
    "action-1",
  );
});

test("search provides loading feedback followed by an honest no-results state", async ({
  page,
}) => {
  const release = await mockAPI(page, { slowSearch: true });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: decision.title }),
  ).toBeVisible();
  await page
    .getByRole("textbox", { name: "Ask your project اسأل مشروعك" })
    .fill("لا يوجد قرار؟");
  await page.getByRole("button", { name: "Search project" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Retrieving and checking",
  );
  release();
  await expect(
    page.getByRole("heading", { name: "No matching results" }),
  ).toBeVisible();
});

test("upload and processing failure retain a clear retry action", async ({
  page,
}) => {
  await mockAPI(page, { upload: true });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: decision.title }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Documents", exact: true }).click();
  await page.getByLabel("Upload documents").setInputFiles({
    name: "notes.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("Project note"),
  });
  await expect(page.locator(".document-row")).toContainText("Uploaded");
  await page.getByRole("button", { name: "Process documents" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "Processing did not finish",
  );
  await expect(
    page.getByRole("button", { name: "Retry processing" }),
  ).toBeEnabled();
  await expect(page.locator(".document-row")).toContainText("Failed");
});

test("API failure offers reconnect without rendering fabricated results", async ({
  page,
}) => {
  await mockAPI(page, { failed: true });
  await page.goto("/");
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "Local API temporarily unavailable",
  );
  await expect(
    page.getByRole("button", { name: "Reconnect & refresh" }),
  ).toBeEnabled();
  await expect(page.locator(".record")).toHaveCount(0);
});

test("mobile evidence is brought into view without horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockAPI(page);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: decision.title }),
  ).toBeVisible();
  await page
    .locator(".record")
    .getByRole("button", { name: "Inspect evidence ↗" })
    .click();
  await expect(
    page.getByRole("complementary", { name: "Source evidence" }),
  ).toBeFocused();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("decision summary uses returned fields and keeps source details collapsed", async ({
  page,
}) => {
  await mockAPI(page, { summary: true });
  await page.goto("/");
  await page
    .getByRole("button", {
      name: "Why did the team replace Falcon Systems?",
      exact: true,
    })
    .click();
  const summary = page.locator(".decision-summary");
  await expect(summary).toContainText("Decision summary");
  expect(await summary.locator("h2").textContent()).toBe(decision.title);
  expect(await summary.locator(".rationale p").textContent()).toBe(
    decision.rationale,
  );
  await expect(summary).toContainText("Verified date · 3 Sept 2026");
  await expect(summary).toContainText(ref.source);
  await expect(page.locator(".more-results")).not.toHaveAttribute("open", "");
  const evidence = page.getByRole("complementary", { name: "Source evidence" });
  await expect(evidence.locator(".badge")).toHaveText("decision");
  await expect(evidence).toContainText("Verified source excerpt");
  expect(await evidence.locator("blockquote").textContent()).toBe(quote);
  await expect(
    evidence.getByText("document-1", { exact: true }),
  ).not.toBeVisible();
  await evidence.getByText("Technical details", { exact: true }).click();
  await expect(evidence.getByText("document-1", { exact: true })).toBeVisible();
});

test("timeline events share one axis on desktop and mobile with isolated Latin runs", async ({
  page,
}) => {
  await mockAPI(page, { timeline: true });
  await page.goto("/");
  await expect(page.locator(".timeline-title")).toHaveCount(2);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    const geometry = await page.locator(".timeline li").evaluateAll((items) =>
      items.map((item) => {
        const title = item.querySelector(".timeline-title")!;
        const date = item.querySelector("time")!;
        return {
          titleX: title.getBoundingClientRect().x,
          dateX: date.getBoundingClientRect().x,
        };
      }),
    );
    expect(Math.abs(geometry[0].titleX - geometry[1].titleX)).toBeLessThan(2);
    expect(Math.abs(geometry[1].titleX - geometry[1].dateX)).toBeLessThan(2);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  await expect(page.locator('.timeline-title bdi[dir="ltr"]')).toHaveText(
    "Nova",
  );
  expect(await page.locator(".timeline-title").allTextContents()).toEqual([
    "Select Falcon Systems",
    decision.title,
  ]);
});

test("risks show only supplied metadata and the loaded demo has truthful navigation", async ({
  page,
}) => {
  await mockAPI(page, { risks: true });
  await page.goto("/");
  const risk = page
    .locator(".risk-record")
    .filter({ hasText: "تأخر Falcon API" });
  await expect(risk).toContainText("Severity: Unknown");
  await expect(risk).toContainText("Status: Open");
  const missing = page
    .locator(".risk-record")
    .filter({ hasText: "No metadata supplied" });
  await expect(missing).not.toContainText("Severity:");
  await expect(missing).not.toContainText("Status:");
  await risk.getByRole("button", { name: "Inspect evidence ↗" }).click();
  await expect(
    page
      .getByRole("complementary", { name: "Source evidence" })
      .locator(".badge"),
  ).toHaveText("risk");
  await expect(
    page.getByRole("button", { name: "Reload demo ↗" }),
  ).toBeVisible();
  await expect(page.getByText("PHASE 05", { exact: true })).toHaveCount(0);
  await expect(
    page.getByText("Local API connected", { exact: true }),
  ).toHaveCount(0);
});
