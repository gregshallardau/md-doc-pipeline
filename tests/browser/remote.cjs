/* Configured remote roots with fifty documents, including Windows-style linked folders. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const net = require("node:net");
const { spawn, spawnSync } = require("node:child_process");
const repository = path.resolve(__dirname, "../..");
const python =
  process.env.MD_DOC_TEST_PYTHON || path.join(repository, ".venv/bin/python");
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

(async () => {
  const temporary = fs.mkdtempSync(
    path.join(os.tmpdir(), "md-doc-remote-browser-"),
  );
  const generated = spawnSync(
    python,
    [
      path.join(repository, "tools/create_remote_editor_demo.py"),
      "--root",
      temporary,
    ],
    { cwd: repository, encoding: "utf8" },
  );
  assert.equal(generated.status, 0, generated.stderr);
  const fixture = JSON.parse(generated.stdout);
  const listener = net.createServer();
  await new Promise((resolve) => listener.listen(0, "127.0.0.1", resolve));
  const port = listener.address().port;
  await new Promise((resolve) => listener.close(resolve));
  const origin = "http://127.0.0.1:" + port;
  const server = spawn(
    python,
    ["-m", "md_doc_web_editor.cli", "--no-browser", "--port", String(port)],
    { cwd: fixture.project, stdio: ["ignore", "pipe", "pipe"] },
  );
  let output = "",
    browser,
    checks = 0;
  for (const stream of [server.stdout, server.stderr])
    stream.on("data", (data) => (output = (output + data).slice(-15000)));
  try {
    for (let attempt = 0; attempt < 100; attempt++) {
      try {
        if ((await fetch(origin)).ok) break;
      } catch {}
      if (server.exitCode !== null) throw new Error(output);
      await pause(100);
    }
    const cached =
      "/home/gregshallard/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome";
    browser = await chromium.launch({
      headless: true,
      ...(process.env.MD_DOC_TEST_BROWSER
        ? { executablePath: process.env.MD_DOC_TEST_BROWSER }
        : fs.existsSync(cached)
          ? { executablePath: cached }
          : {}),
    });
    const page = await browser.newPage({
      viewport: { width: 1500, height: 1000 },
    });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    for (const [name, expectedRoot] of [
      ["affinity-demo", fixture.remote],
      ["affinity-linked-demo", fixture.linkedRemote],
    ]) {
      await page.goto(origin + "/?workspace=" + name);
      await page.waitForFunction(
        () =>
          document.querySelector("#tree-document-count").textContent === "50",
      );
      assert.equal(
        await page.locator("#workspace-path").textContent(),
        expectedRoot,
      );
      checks++;
      assert.equal(
        await page
          .locator("#md-doc-tree > .tree-list > li > .tree-folder")
          .count(),
        15,
      );
      checks++;
      await page.locator('[data-action="expand-folders"]').click();
      assert.equal(await page.locator(".tree-file.md:visible").count(), 50);
      checks++;
      assert(await page.locator('[data-path="_meta.yml"]').isVisible());
      assert(await page.locator('[data-path="_pdf-theme.css"]').isVisible());
      checks++;
      const document = page
        .locator(".tree-file.md")
        .filter({ hasText: "document-01.md" })
        .first();
      await document.click();
      await page.waitForFunction(
        () =>
          document.querySelector("#preview-status").textContent === "Current",
        null,
        { timeout: 30000 },
      );
      assert((await page.locator(".pdfViewer .page").count()) > 0);
      await page.waitForFunction(
        () =>
          [...document.querySelectorAll(".textLayer")]
            .map((node) => node.textContent)
            .join("")
            .replace(/\s+/g, "")
            .includes("Affinitydocument01"),
        null,
        { timeout: 15000 },
      );
      checks++;
      await page.screenshot({
        path: path.join(os.tmpdir(), name + ".png"),
        fullPage: true,
      });
    }
    assert.deepEqual(errors, []);
    console.log(
      checks +
        " remote browser checks passed: 15 folders and 50 files in ordinary and linked workspaces, with real PDF previews",
    );
  } catch (error) {
    console.error(output);
    throw error;
  } finally {
    if (browser) await browser.close();
    server.kill("SIGINT");
    await pause(300);
    if (server.exitCode === null) server.kill("SIGKILL");
    fs.rmSync(temporary, { recursive: true, force: true });
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
