import { test, expect } from "@playwright/test";

test("intake, price change, explicit approval and evidence-gated outcome", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Start coordinating" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("landing.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(await page.evaluate(() => innerWidth));
  await page.getByRole("button", { name: "Start coordinating" }).click();
  await expect(
    page.getByRole("heading", { name: "A decision for you" }),
  ).toBeVisible({ timeout: 15000 });
  await expect(page.getByText("FIXTURE MODE", { exact: true })).toBeVisible();
  const decision = await page.locator(".approval-card").boundingBox();
  const providers = await page
    .getByRole("heading", { name: "Compare providers" })
    .boundingBox();
  expect(decision!.y).toBeLessThan(700);
  expect(decision!.y).toBeLessThanOrEqual(providers!.y + 50);
  await page.getByRole("tab", { name: "Evidence", exact: false }).click();
  await expect(
    page.getByRole("heading", { name: "Evidence library" }),
  ).toBeVisible();
  await expect(page.locator("#workspace-panel .approval-card")).toHaveCount(0);
  await page.getByRole("tab", { name: "The plan" }).click();
  await expect(
    page.getByRole("heading", { name: "The plan", exact: true }),
  ).toBeVisible();
  await expect(page.locator("#workspace-panel .approval-card")).toHaveCount(0);
  await page.getByRole("tab", { name: "Overview" }).click();
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
  // The gallery puts the current proposal first, so find Ace by name, not position.
  await page
    .locator(".provider-card", { hasText: "Ace Appliance Repair" })
    .getByRole("button", { name: "$190.00" })
    .click();
  await expect(page.getByRole("dialog")).toContainText("$70 trip charge");
  await page.getByRole("button", { name: "Close evidence" }).click();
  await page
    .getByRole("button", { name: "Inject duplicate of last message" })
    .click();
  await page.getByRole("tab", { name: "Activity" }).click();
  await expect(
    page.getByText("Duplicate provider message ignored.").first(),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Overview" }).click();
  await expect(
    page.getByRole("button", { name: "Approve these terms" }),
  ).toBeVisible({ timeout: 10000 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: testInfo.outputPath("proposal.png"),
    fullPage: true,
  });
  await expect(page.getByText("Handled ✓", { exact: true })).toHaveCount(0);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(await page.evaluate(() => innerWidth));
  await page.getByRole("button", { name: "Approve these terms" }).click();
  await expect(page.getByText("Handled ✓", { exact: true })).toBeVisible({
    timeout: 10000,
  });
  await expect(
    page.getByRole("heading", { name: "Compare providers" }),
  ).not.toBeVisible();
  await page.getByRole("tab", { name: "The plan" }).click();
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
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({
    path: testInfo.outputPath("completed.png"),
    fullPage: true,
  });
  await page.getByRole("link", { name: "Your outcomes", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Your outcomes" }),
  ).toBeVisible();
  await page.reload();
  await expect(page.locator(".outcome-list a")).toHaveCount(1);
});

for (const fault of ["mismatch", "no_confirmation"] as const) {
  test(`${fault} evidence never completes the task`, async ({ page }) => {
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
      .selectOption(fault);
    await page.getByRole("button", { name: "Approve these terms" }).click();
    await expect(
      page.getByText(
        fault === "mismatch"
          ? "Booking does not match what you approved — not complete"
          : "Confirmation evidence is still missing",
      ),
    ).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("Handled ✓", { exact: true })).toHaveCount(0);
    await expect(
      page.getByRole("link", { name: "Revise as a new request" }),
    ).toHaveCount(0);
  });
}

test("a rejected proposal can be revised or stopped, with the original retained", async ({
  page,
}) => {
  await page.goto("/tasks/tsk_demo");
  // Rejecting is "Not this one — find another" (roadmap A); the offline mock can't
  // re-coordinate, so it offers revise / stop.
  const reject = page.getByRole("button", { name: /Not this one/ });
  await expect(reject).toBeVisible({ timeout: 15000 });
  await reject.click();
  await expect(
    page.getByRole("heading", { name: "Choose your next step" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Revise as a new request" }).click();
  await expect(
    page.getByRole("heading", { name: "Revise your request" }),
  ).toBeVisible();
  const budget = page.getByLabel("Maximum visit charge (USD)");
  await expect(budget).toHaveValue("150");
  await budget.fill("175");
  await expect(page.locator(".request-summary")).toContainText("$175.00");
  await page.getByRole("link", { name: "Back to original request" }).click();
  await page
    .getByRole("button", { name: "Stop coordination", exact: true })
    .click();
  await expect(
    page.getByText("Coordination stopped.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve these terms" }),
  ).toHaveCount(0);
});

test("validation focuses the invalid field and missing tasks stop loading", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Start coordinating" }).waitFor();
  await page.getByLabel("What needs doing?").fill("");
  await page.getByRole("button", { name: "Start coordinating" }).click();
  await expect(page.getByLabel("What needs doing?")).toBeFocused();
  await expect(page.getByLabel("What needs doing?")).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await page.goto("/tasks/missing-task");
  await expect(
    page.getByRole("heading", { name: "Outcome not found" }),
  ).toBeVisible();
  await expect(page.locator(".loading-orbit")).toHaveCount(0);
});
