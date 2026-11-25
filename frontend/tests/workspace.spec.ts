import { expect, test } from "@playwright/test";

const model = (id: string) => ({
  provider: "opencode",
  id,
  provider_name: "OpenCode",
  name: id,
  free: true,
  requires_key: false,
  available: true,
});

test("loads the comparison workspace with mocked API data", async ({
  page,
}) => {
  await page.route("**/api/models", (route) =>
    route.fulfill({ json: [model("Free A"), model("Free B")] }),
  );
  await page.route("**/api/integrations", (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route("**/api/comparisons", (route) =>
    route.fulfill({
      json: {
        id: "ui-test",
        token: "mock-session-token",
        expires_in: 600,
        runs: {
          a: {
            model: "Free A",
            provider: "OpenCode",
            status: "running",
            preview_url: null,
          },
          b: {
            model: "Free B",
            provider: "OpenCode",
            status: "running",
            preview_url: null,
          },
        },
      },
    }),
  );
  await page.routeWebSocket("**/api/comparisons/ui-test/events", () => {});
  await page.goto("/");
  await page
    .getByLabel("Application prompt")
    .fill("Build a responsive web app.");
  await page.getByLabel("Model A").selectOption("opencode/Free A");
  await page.getByLabel("Model B").selectOption("opencode/Free B");
  await page.getByRole("button", { name: "Start comparison" }).click();
  await expect(
    page.getByRole("heading", { name: "Comparison workspace" }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Application A" }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Application B" }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole("button", { name: "Application B", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Application B" }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Application A" }),
  ).toBeHidden();
  await page.getByRole("button", { name: "Use light theme" }).click();
  await expect(
    page.getByRole("button", { name: "Use dark theme" }),
  ).toBeVisible();
});

test("generates, interacts with, exports and removes two real apps", async ({
  page,
  request,
}) => {
  test.skip(
    process.env.VB_REAL_SMOKE !== "1",
    "Requires local Docker and real OpenCode providers",
  );
  const response = await request.get("/api/models");
  expect(response.ok()).toBeTruthy();
  const data: Array<{ free: boolean; provider: string; id: string }> =
    await response.json();
  const free = data
    .filter((item) => item.free)
    .map((item) => item.provider + "/" + item.id);
  const a = process.env.VB_SMOKE_MODEL_A ?? free[0];
  const b = process.env.VB_SMOKE_MODEL_B ?? free.find((value) => value !== a);
  expect(a).toBeTruthy();
  expect(b).toBeTruthy();

  await page.goto("/");
  await page
    .getByLabel("Application prompt")
    .fill(
      'Build a tiny static web app with index.html and vanilla JavaScript. Show a heading named Horse Discovery and a button named Favorite. Clicking Favorite must display "Saved!". Serve it using Python http.server so no dependencies are needed.',
    );
  await page.getByLabel("Model A").selectOption(a!);
  await page.getByLabel("Model B").selectOption(b!);
  await page.getByRole("button", { name: "Start comparison" }).click();
  try {
    await expect(
      page.getByRole("heading", { name: "Comparison workspace" }),
    ).toBeVisible();
    const urls = new Set<string>();
    for (const side of ["A", "B"]) {
      const iframe = page.locator('iframe[title="Application ' + side + '"]');
      const panel = page.getByRole("region", { name: "Application " + side });
      const failure = panel.getByText("failed", { exact: true });
      await expect(iframe.or(failure).first()).toBeVisible({
        timeout: 220_000,
      });
      if (await failure.isVisible()) {
        await panel.getByRole("button", { name: "Agent activity" }).click();
        throw new Error(
          "Agent " +
            side +
            " failed. " +
            (await panel.getByRole("log").innerText()),
        );
      }
      urls.add((await iframe.getAttribute("src"))!);
      const app = page.frameLocator('iframe[title="Application ' + side + '"]');
      await expect(
        app.getByRole("heading", { name: /Horse Discovery/i }),
      ).toBeVisible();
      await app.getByRole("button", { name: "Favorite", exact: true }).click();
      await expect(app.getByText("Saved!", { exact: true })).toBeVisible();
    }
    expect(urls.size).toBe(2);
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export both" }).click();
    expect((await download).suggestedFilename()).toBe("vibebench-both.zip");
    await page.getByRole("button", { name: "End session" }).click();
    await expect(
      page.getByRole("button", { name: "Start comparison" }),
    ).toBeVisible();
    for (const url of urls) expect((await request.get(url)).status()).toBe(404);
  } finally {
    const end = page.getByRole("button", { name: "End session" });
    if (await end.isVisible()) await end.click().catch(() => {});
  }
});
