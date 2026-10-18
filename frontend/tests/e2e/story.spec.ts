import { test, expect } from "@playwright/test";
test("intake, price change, explicit approval and evidence-gated outcome", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Start coordinating" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("intake.png"),
    fullPage: true,
    animations: "disabled",
  });
  const landingWidth = await page.evaluate(() => ({
    body: document.documentElement.scrollWidth,
    viewport: innerWidth,
  }));
  expect(landingWidth.body).toBeLessThanOrEqual(landingWidth.viewport);
  await page
    .getByRole("button", { name: "Pause illustration animation" })
    .click();
  await expect(page.getByTestId("illustration-orbit")).toHaveCSS(
    "animation-play-state",
    "paused",
  );
  await page
    .getByRole("button", { name: "Play illustration animation" })
    .click();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(page.getByTestId("illustration-orbit")).toHaveCSS(
    "animation-name",
    "none",
  );
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  await page.screenshot({
    path: testInfo.outputPath("landing-viewport.png"),
    animations: "disabled",
  });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.getByRole("button", { name: "Start coordinating" }).click();
  await expect(
    page.getByRole("heading", { name: "A decision for you" }),
  ).toBeVisible({ timeout: 15000 });
  await expect(page.getByText("FIXTURE MODE", { exact: true })).toBeVisible();
  await page
    .locator("summary")
    .filter({ hasText: "Presenter controls" })
    .click();
  await page.getByRole("button", { name: /Inject: Provider A/ }).click();
  await expect(
    page.getByRole("heading", { name: "Previous approval withdrawn" }),
  ).toBeVisible();
  await expect(
    page.locator("del").filter({ hasText: "$120.00" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Inject duplicate of last message" })
    .click();
  await expect(
    page.getByText("Duplicate provider message ignored.").first(),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve these terms" }),
  ).toBeVisible({ timeout: 10000 });
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  await page.screenshot({
    path: testInfo.outputPath("workspace-viewport.png"),
    animations: "disabled",
  });
  await page.screenshot({
    path: testInfo.outputPath("replanned.png"),
    fullPage: true,
    animations: "disabled",
  });
  await expect(page.getByText("Handled ✓", { exact: true })).toHaveCount(0);
  const width = await page.evaluate(() => ({
    body: document.documentElement.scrollWidth,
    window: innerWidth,
  }));
  expect(width.body).toBeLessThanOrEqual(width.window);
  await page.getByRole("button", { name: "Approve these terms" }).click();
  await expect(page.getByText("Handled ✓", { exact: true })).toBeVisible({
    timeout: 10000,
  });
  await page.getByRole("tab", { name: "The plan" }).click();
  await expect(
    page.getByRole("heading", { name: "The plan", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "The plan" }).press("ArrowLeft");
  await expect(page.getByRole("tab", { name: /Evidence/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.getByRole("button").filter({ hasText: "Portal record" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByText("BK-MOCK-145", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Close evidence" }).click();
  await page.getByRole("tab", { name: "Overview" }).click();
  await page.screenshot({
    path: testInfo.outputPath("completed.png"),
    fullPage: true,
    animations: "disabled",
  });
});
test("mismatched portal evidence never completes the task", async ({
  page,
}) => {
  await page.goto("/tasks/tsk_demo?demo=1");
  await expect(
    page.getByRole("heading", { name: "A decision for you" }),
  ).toBeVisible({ timeout: 15000 });
  await page
    .locator("summary")
    .filter({ hasText: "Presenter controls" })
    .click();
  await page.getByRole("button", { name: /Inject: Provider A/ }).click();
  await page
    .getByLabel("Portal fault (set before approving Bayside)")
    .selectOption("mismatch");
  await expect(
    page.getByRole("button", { name: "Approve these terms" }),
  ).toBeVisible({ timeout: 10000 });
  await page.getByRole("button", { name: "Approve these terms" }).click();
  await expect(
    page.getByText("Booking does not match what you approved — not complete"),
  ).toBeVisible({ timeout: 10000 });
  await expect(page.getByText("Handled ✓", { exact: true })).toHaveCount(0);
});
