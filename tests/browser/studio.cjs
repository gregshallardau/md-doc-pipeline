/* Real offline studio: Monaco, pipeline snapshots, PDF.js and Git in a disposable project. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const net = require("node:net");
const { spawn, spawnSync } = require("node:child_process");
const root = path.resolve(__dirname, "../..");
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let checks = 0;
function check(condition, message) {
  assert(condition, message);
  checks++;
}
(async () => {
  const project = fs.mkdtempSync(path.join(os.tmpdir(), "md-doc-studio-"));
  const workspace = path.join(project, "documents");
  fs.mkdirSync(workspace);
  fs.mkdirSync(path.join(project, "templates"));
  const git = (...args) => {
    const result = spawnSync("git", ["-C", project, ...args], {
      encoding: "utf8",
    });
    assert.equal(result.status, 0, result.stderr);
    return result.stdout;
  };
  git("init");
  git("config", "user.name", "Studio Browser Test");
  git("config", "user.email", "studio@example.test");
  fs.writeFileSync(
    path.join(project, "_meta.yml"),
    "product: Original\nauthor: Studio Browser Test\ndate: 8 October 2026\n",
  );
  fs.copyFileSync(
    path.join(root, "examples/feature-showcase/_theme.css"),
    path.join(project, "_theme.css"),
  );
  fs.writeFileSync(
    path.join(project, "templates/shared.md"),
    "Included baseline\n",
  );
  fs.writeFileSync(
    path.join(project, "_merge_fields.yml"),
    "contact_name: Primary contact name\n",
  );
  const original =
    '---\ncover_page: true\n---\n# Snapshot {{ product }}\n\n## First section\n\n{% include "shared.md" %}\n\nA simple paragraph.\n\n<!-- pagebreak -->\n\n## Second section\n\nFinal paragraph.\n';
  fs.writeFileSync(path.join(workspace, "doc.md"), original);
  fs.writeFileSync(
    path.join(workspace, "second.md"),
    "# Second document\n\nA second paragraph.\n",
  );
  fs.mkdirSync(path.join(workspace, "reports"));
  fs.writeFileSync(
    path.join(workspace, "reports", "nested.md"),
    "# Nested report\n",
  );
  git("add", ".");
  git("commit", "-m", "Initial samples");
  const listener = net.createServer();
  await new Promise((r) => listener.listen(0, "127.0.0.1", r));
  const port = listener.address().port;
  await new Promise((r) => listener.close(r));
  const origin = `http://127.0.0.1:${port}`;
  const server = spawn(
    process.env.MD_DOC_TEST_PYTHON || path.join(root, ".venv/bin/python"),
    [
      "-c",
      "import mimetypes; mimetypes.add_type('text/plain', '.js'); mimetypes.add_type('application/octet-stream', '.mjs'); from md_doc_web_editor.cli import main; raise SystemExit(main())",
      "serve",
      workspace,
      "--no-browser",
      "--port",
      String(port),
    ],
    { cwd: root, stdio: ["ignore", "pipe", "pipe"] },
  );
  let output = "";
  server.stdout.on("data", (chunk) => {
    output = (output + chunk).slice(-30000);
  });
  server.stderr.on("data", (chunk) => {
    output = (output + chunk).slice(-30000);
  });
  let browser, testPage;
  try {
    let ready = false;
    for (let i = 0; i < 100; i++) {
      try {
        if ((await fetch(origin)).ok) {
          ready = true;
          break;
        }
      } catch {}
      if (server.exitCode !== null) throw new Error(output);
      await delay(100);
    }
    check(ready, output);
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
    const context = await browser.newContext({
      viewport: { width: 1480, height: 980 },
      serviceWorkers: "block",
    });
    const external = [],
      errors = [];
    await context.route("**/*", (route) => {
      const url = new URL(route.request().url());
      if (
        url.origin !== origin &&
        !["data:", "blob:", "about:"].includes(url.protocol)
      ) {
        external.push(url.href);
        return route.abort();
      }
      return route.continue();
    });
    const page = await context.newPage();
    testPage = page;
    page.on("pageerror", (error) => errors.push(error.stack || error.message));
    await page.goto(origin);
    await page.locator('[data-path="doc.md"]').waitFor();
    check(
      await page.locator('[data-path="reports/nested.md"]').isVisible(),
      "Nested documents are visible on first launch",
    );
    check(
      (await page.locator("#tree-document-count").textContent()) === "3",
      "Workspace document count is visible",
    );
    check(
      (await page
        .locator(".tree-folder summary .document-count")
        .first()
        .textContent()) === "1",
      "Folders show document counts",
    );
    // One input switches between fuzzy file search and commands via >.
    await page.keyboard.press("Control+p");
    check(
      (await page.locator("#command-query").inputValue()) === "",
      "Quick open starts in file mode",
    );
    await page.locator("#command-query").fill("scnd");
    check(
      (await page
        .locator("#command-results .command-item strong")
        .first()
        .textContent()) === "second.md",
      "File search fuzzy-matches names",
    );
    await page.locator("#command-query").fill("> chly");
    check(
      (await page
        .locator("#command-results .command-item strong")
        .first()
        .textContent()) === "Change layout",
      "Leading > fuzzy-matches commands in the same bar",
    );
    check(
      (await page.locator("#command-results").textContent()).includes(
        "Command",
      ) &&
        !(await page.locator("#command-results").textContent()).includes(
          "second.md",
        ),
      "Command mode excludes file results",
    );
    await page.locator("#command-query").fill("rptsnstd");
    check(
      (await page.locator("#command-results").textContent()).includes(
        "reports/nested.md",
      ),
      "Removing > switches to fuzzy path search",
    );
    await page.locator("#command-query").fill("no-such-file-xyz");
    await page.keyboard.press("Enter");
    check(
      await page.locator("#command-dialog").isVisible(),
      "Enter with no results keeps the search open",
    );
    await page.keyboard.press("Control+Shift+p");
    check(
      (await page.locator("#command-query").inputValue()) === "> ",
      "Command shortcut prefills > in the existing bar",
    );
    await page.keyboard.press("ArrowDown");
    check(
      (await page
        .locator("#command-query")
        .getAttribute("aria-activedescendant")) === "command-option-1" &&
        (await page
          .locator("#command-option-1")
          .getAttribute("aria-selected")) === "true",
      "Keyboard selection exposes the active command option",
    );
    await page.locator("#command-query").fill("second.md");
    await page.keyboard.press("Enter");
    await page.waitForFunction(() =>
      monaco.editor.getEditors()[0].getValue().includes("Second document"),
    );
    check(
      !(await page.locator("#command-dialog").isVisible()),
      "Enter opens the selected file from the unified bar",
    );
    await page.keyboard.press("F1");
    check(
      (await page.locator("#command-query").inputValue()) === "> ",
      "F1 opens command mode",
    );
    await page.keyboard.press("Escape");
    await page.locator('[data-path="doc.md"]').click();
    await page.waitForFunction(() =>
      monaco.editor.getEditors()[0].getValue().includes("Snapshot"),
    );
    check(
      (
        await page.locator("#document-tabs .tab-name").allTextContents()
      ).join() === "doc.md",
      "Browsing another file replaces the unedited tab",
    );
    await page.evaluate(() => {
      const editor = monaco.editor.getEditors()[0];
      editor.executeEdits("test", [
        { range: new monaco.Range(1, 1, 1, 1), text: "Temporary tab edit\n" },
      ]);
      editor.trigger("test", "undo", null);
    });
    await page.locator('[data-path="second.md"]').click();
    await page.waitForFunction(() =>
      monaco.editor.getEditors()[0].getValue().includes("Second document"),
    );
    check(
      (
        await page.locator("#document-tabs .tab-name").allTextContents()
      ).includes("doc.md"),
      "An edited tab stays open even after its changes are undone",
    );
    await page.locator('[data-path="doc.md"]').click();
    await page.waitForFunction(() =>
      monaco.editor.getEditors()[0].getValue().includes("Snapshot"),
    );
    await page.locator('[data-nav="files"]').click();
    check(
      await page
        .locator("#workbench")
        .evaluate((node) => node.classList.contains("nav-hidden")),
      "Files rail collapses its sidebar",
    );
    check(
      Math.abs((await page.locator("#editor-pane").boundingBox()).x - 46) < 1,
      "Collapsed sidebar leaves no blank navigation track",
    );
    await page.locator('[data-nav="files"]').click();
    check(
      await page.locator("#sidebar").isVisible(),
      "Files rail reopens its sidebar",
    );
    await page.locator('[data-action="collapse-folders"]').click();
    check(
      !(await page.locator('[data-path="reports/nested.md"]').isVisible()),
      "Collapse all hides nested documents",
    );
    await page.locator('[data-action="expand-folders"]').click();
    check(
      await page.locator('[data-path="reports/nested.md"]').isVisible(),
      "Expand all reveals nested documents",
    );
    await page.locator("#appearance-button").click();
    check(
      (await page.locator("html").getAttribute("data-theme")) === "dark" &&
        (await page.locator("#appearance-label").textContent()) ===
          "Light mode",
      "Visible theme control applies dark mode",
    );
    await page.locator("#appearance-button").click();
    check(
      (await page.locator("html").getAttribute("data-theme")) === "light",
      "Theme control restores light mode",
    );
    await page.locator("#tree-root-toggle").click();
    check(
      !(await page.locator("#md-doc-tree").isVisible()),
      "Workspace root collapses its file list",
    );
    await page.locator("#tree-root-toggle").click();
    check(
      await page.locator("#md-doc-tree").isVisible(),
      "Workspace root reopens its file list",
    );
    await page.locator("#workspace-button").click();
    await page
      .getByRole("button", { name: "Choose document folder", exact: true })
      .click();
    await page
      .locator(".workspace-folder")
      .filter({ hasText: "reports" })
      .click();
    await page
      .locator("#dialog-body .workspace-choice-path")
      .filter({ hasText: path.join(workspace, "reports") })
      .waitFor();
    check(
      (await page
        .locator("#dialog-body .workspace-choice-path")
        .textContent()) === path.join(workspace, "reports"),
      "Directory chooser displays the exact nested path",
    );
    check(
      (
        await page
          .getByRole("link", { name: "Open this directory", exact: true })
          .getAttribute("href")
      ).includes("folder=reports"),
      "Directory chooser opens the selected root",
    );
    await page.locator("#dialog-close").click();
    await page.evaluate(async () => {
      const module = await import("/static/viewer.js");
      const load = module.DocumentViewer.prototype.load;
      module.DocumentViewer.prototype.load = function (...args) {
        window.studioTestViewer = this;
        return load.apply(this, args);
      };
    });
    await page.locator('[data-path="doc.md"]').click();
    await page.waitForFunction(
      () => document.querySelector("#preview-status").textContent === "Current",
      null,
      { timeout: 30000 },
    );
    await page.waitForFunction(() =>
      document
        .querySelector(".pdfViewer .textLayer")
        ?.textContent.includes("Snapshot Original"),
    );
    check(
      (await page.locator(".pdfViewer .page").count()) === 3,
      "Full cover and two content pages",
    );
    check(
      (await page.locator(".md-doc-local-editor").count()) === 0,
      "Real Monaco loads",
    );
    check(
      (await page.locator("#pdf-total").textContent()) === "3",
      "Viewer page count",
    );
    const source = () =>
      page.evaluate(() => monaco.editor.getEditors()[0].getValue());
    const edit = (content) =>
      page.evaluate(
        (content) => monaco.editor.getEditors()[0].getModel().setValue(content),
        content,
      );
    await edit(
      original.replace("A simple paragraph.", "Unsaved source paragraph."),
    );
    await page.waitForFunction(
      () => document.querySelector("#preview-status").textContent === "Current",
      null,
      { timeout: 30000 },
    );
    check(
      fs.readFileSync(path.join(workspace, "doc.md"), "utf8") === original,
      "Preview never saves source",
    );
    // Actual PDF download is the same immutable artifact displayed by the viewer.
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page
        .getByRole("button", { name: "Download displayed PDF", exact: true })
        .click(),
    ]);
    const artifact = fs.readFileSync(await download.path());
    check(
      artifact.subarray(0, 4).toString() === "%PDF",
      "Artifact download is PDF",
    );
    // Check actual navigation geometry, not just the moving splitter.
    const sidebar = page.locator("#sidebar");
    const navBefore = await sidebar.boundingBox();
    const navSplit = await page.locator("#nav-splitter").boundingBox();
    await page.mouse.move(navSplit.x + 2, navSplit.y + 150);
    await page.mouse.down();
    await page.mouse.move(navSplit.x + 102, navSplit.y + 150, { steps: 8 });
    await page.mouse.up();
    const navAfter = await sidebar.boundingBox();
    const movedSplit = await page.locator("#nav-splitter").boundingBox();
    check(
      navAfter.width > navBefore.width + 90,
      "Pointer resize grows the actual sidebar",
    );
    check(
      Math.abs(navAfter.x + navAfter.width - movedSplit.x) < 1,
      "Sidebar edge follows the drag handle",
    );
    await page.locator("#nav-splitter").focus();
    await page.keyboard.press("ArrowLeft");
    check(
      (await sidebar.boundingBox()).width < navAfter.width,
      "Keyboard resize shrinks the actual sidebar",
    );
    await page.locator("#nav-splitter").dblclick();
    check(
      Math.abs((await sidebar.boundingBox()).width - 240) < 1,
      "Double click restores the sidebar width",
    );
    // Resizing works by pointer and keyboard, and persists through reload.
    const editor = page.locator("#editor-pane");
    const before = (await editor.boundingBox()).width;
    const split = await page.locator("#preview-splitter").boundingBox();
    await page.mouse.move(split.x + 2, split.y + 150);
    await page.mouse.down();
    await page.mouse.move(split.x + 100, split.y + 150, { steps: 8 });
    await page.mouse.up();
    check(
      (await editor.boundingBox()).width > before + 60,
      "Pointer splitter grows source pane",
    );
    await page.locator("#preview-splitter").focus();
    const pointerWidth = (await editor.boundingBox()).width;
    await page.keyboard.press("ArrowLeft");
    check(
      (await editor.boundingBox()).width < pointerWidth,
      "Keyboard splitter adjusts panes",
    );
    const resized = (await editor.boundingBox()).width;
    // Tabs keep separate unsaved buffers instead of discarding on navigation.
    await page.locator('[data-path="second.md"]').click();
    await page.locator('[data-path="doc.md"]').click();
    check(
      (await source()).includes("Unsaved source paragraph."),
      "Tabs retain unsaved buffer",
    );
    await page.reload();
    await page.waitForFunction(() =>
      window.monaco?.editor
        .getEditors()[0]
        ?.getValue()
        .includes("Unsaved source paragraph."),
    );
    check(
      Math.abs((await editor.boundingBox()).width - resized) < 4,
      "Layout restored",
    );
    check(
      fs.readFileSync(path.join(workspace, "doc.md"), "utf8") === original,
      "Recovered draft is not silently saved",
    );
    // Inspect and edit an ancestor dependency while keeping the document pinned.
    await page
      .getByRole("button", { name: "Document properties", exact: true })
      .click();
    await page.waitForSelector("#prop-title");
    await page.locator('[data-inspect="fields"]').click();
    check(
      await page
        .getByRole("button", { name: "{{ product }}", exact: true })
        .isVisible(),
      "Fields offers resolved metadata values",
    );
    check(
      await page
        .getByRole("button", { name: "[[contact_name]]", exact: true })
        .isVisible(),
      "Fields distinguishes Word placeholders",
    );
    const beforeFieldInsertion = await source();
    await page
      .getByRole("button", { name: "{{ product }}", exact: true })
      .click();
    check(
      (await source()).length ===
        beforeFieldInsertion.length + "{{ product }}".length,
      "Metadata insertion uses Jinja syntax",
    );
    await edit(beforeFieldInsertion);
    await page.locator('[data-inspect="properties"]').click();

    await page.locator(".layer summary").first().click();
    await page
      .getByRole("button", { name: "Open source", exact: true })
      .first()
      .click();
    await page.waitForFunction(() =>
      monaco.editor.getEditors()[0].getValue().includes("product: Original"),
    );
    await edit(
      "product: UnsavedBrand\nauthor: Studio Browser Test\ndate: 8 October 2026\n",
    );
    await page
      .getByRole("button", { name: "Close inspector", exact: true })
      .click();
    await page.waitForFunction(
      () => document.querySelector("#preview-status").textContent === "Current",
      null,
      { timeout: 30000 },
    );
    await page.waitForFunction(() =>
      document
        .querySelector(".pdfViewer .textLayer")
        ?.textContent.includes("Snapshot UnsavedBrand"),
    );
    check(
      fs
        .readFileSync(path.join(project, "_meta.yml"), "utf8")
        .includes("product: Original"),
      "Unsaved ancestor metadata remains on disk",
    );
    check(
      (await page.locator("#preview-document").textContent()) === "doc.md",
      "Document preview stays pinned during config edits",
    );
    // Expand templates in the same Monaco model, with source-aware edits.
    fs.writeFileSync(
      path.join(project, "templates/nested.html"),
      "<h3>Nested section</h3>\n",
    );
    await page.locator('[data-path="doc.md"]').click();
    await page.evaluate(() => {
      const editor = monaco.editor.getEditors()[0];
      const line =
        editor
          .getValue()
          .split("\n")
          .findIndex((line) => line.includes("{% include")) + 1;
      editor.revealLineInCenter(line);
    });
    await page.locator(".template-include-link").first().click();
    await page.waitForSelector(".source-expansion-bar");
    check(
      (await source()).includes("Snapshot") &&
        (await source()).includes("Included baseline"),
      "The main document expands to include the upstream source text",
    );
    check(
      (await page.evaluate(() => monaco.editor.getEditors().length === 1)) &&
        (await page.locator(".template-peek").count()) === 0,
      "Expanded templates use one editor with no sub-editor or striped view zone",
    );
    check(
      (await page.locator(".expanded-source-name").textContent()).includes(
        "project:templates/shared.md",
      ),
      "The source indicator identifies the upstream file under the cursor",
    );
    await page
      .getByRole("button", { name: "Switch appearance", exact: true })
      .click();
    check(
      await page.evaluate(
        () =>
          document.documentElement.dataset.theme === "dark" &&
          monaco.editor
            .getEditors()[0]
            .getDomNode()
            .classList.contains("vs-dark"),
      ),
      "Expanded source shares the main editor's dark theme",
    );
    await page
      .getByRole("button", { name: "Collapse templates", exact: true })
      .click();
    check(
      !(await source()).includes("Included baseline"),
      "Collapsing restores the original source include declaration",
    );
    await page.locator(".template-include-link").first().click();
    await page.waitForSelector(".source-expansion-bar");
    check(
      await page.evaluate(
        () =>
          monaco.editor.getEditors().length === 1 &&
          monaco.editor
            .getEditors()[0]
            .getDomNode()
            .classList.contains("vs-dark"),
      ),
      "Re-expansion retains the editor theme and single editing surface",
    );
    await page
      .getByRole("button", { name: "Switch appearance", exact: true })
      .click();
    const jobRequests = [];
    const recordPreview = (request) => {
      if (
        request.method() === "POST" &&
        request.url().includes("/api/preview/jobs")
      )
        jobRequests.push(request);
    };
    await page.waitForFunction(
      () => document.querySelector("#preview-status").textContent === "Current",
    );
    page.on("request", recordPreview);
    const fragmentDraft =
      '## Included inline draft\n\n{% include "nested.html" %}\n';
    await page.evaluate((text) => {
      const editor = monaco.editor.getEditors()[0],
        model = editor.getModel();
      const start = model.getValue().indexOf("Included baseline\n");
      const from = model.getPositionAt(start),
        to = model.getPositionAt(start + "Included baseline\n".length);
      editor.executeEdits("template-test", [
        {
          range: new monaco.Range(
            from.lineNumber,
            from.column,
            to.lineNumber,
            to.column,
          ),
          text,
        },
      ]);
    }, fragmentDraft);
    await page.waitForTimeout(900);
    check(
      jobRequests.length === 0,
      "Preview waits for the longer typing pause",
    );
    await page.waitForFunction(
      () => document.querySelector("#preview-status").textContent === "Current",
    );
    await page.locator("#pdf-page").fill("2");
    await page.locator("#pdf-page").press("Enter");
    await page.waitForFunction(() =>
      [...document.querySelectorAll(".textLayer")].some((node) =>
        node.textContent.includes("Included inline draft"),
      ),
    );
    page.off("request", recordPreview);
    check(
      fs.readFileSync(path.join(project, "templates/shared.md"), "utf8") ===
        "Included baseline\n",
      "Expanded template drafts preview without writing the upstream file",
    );
    const draftRequest = jobRequests.at(-1).postDataJSON();
    check(
      draftRequest.buffers["project:templates/shared.md"] === fragmentDraft &&
        !(draftRequest.buffers["doc.md"] || "").includes(
          "Included inline draft",
        ),
      "Preview receives separate source buffers rather than flattened template text in the parent",
    );
    check(
      (await page.locator("#preview-document").textContent()) === "doc.md",
      "Expanded edits keep the final document PDF pinned",
    );
    await page.locator('[data-nav="outline"]').click();
    await page
      .getByRole("button", { name: "Included inline draft", exact: true })
      .waitFor();
    check(
      (await page.locator(".outline-document").textContent()).includes(
        "Snapshot UnsavedBrand",
      ) && !(await page.locator(".tree-controls").isVisible()),
      "Outline context describes the final document rather than workspace folder controls",
    );
    check(
      (await page
        .getByRole("button", { name: "Nested section", exact: true })
        .isVisible()) &&
        (await page
          .getByRole("button", { name: "Snapshot UnsavedBrand", exact: true })
          .isVisible()),
      "The composed outline includes resolved titles and nested HTML template headings",
    );
    await page
      .getByRole("button", { name: "Nested section", exact: true })
      .click();
    await page.waitForFunction(() =>
      monaco.editor
        .getEditors()[0]
        .getValue()
        .includes("<h3>Nested section</h3>"),
    );
    check(
      await page.evaluate(() => {
        const editor = monaco.editor.getEditors()[0];
        return (
          editor
            .getModel()
            .getLineContent(editor.getPosition().lineNumber)
            .includes("Nested section") &&
          monaco.editor.getEditors().length === 1
        );
      }),
      "Outline navigation expands the nested source and places the cursor on its heading",
    );
    await page.evaluate(() => {
      const editor = monaco.editor.getEditors()[0],
        model = editor.getModel();
      const start = model.getValue().indexOf("Nested section");
      const from = model.getPositionAt(start),
        to = model.getPositionAt(start + "Nested section".length);
      editor.pushUndoStop();
      editor.executeEdits("nested-test", [
        {
          range: new monaco.Range(
            from.lineNumber,
            from.column,
            to.lineNumber,
            to.column,
          ),
          text: "Nested edited",
        },
      ]);
      editor.pushUndoStop();
      editor.trigger("nested-test", "undo", null);
    });
    check(
      (await source()).includes("Nested section") &&
        !(await source()).includes("Nested edited"),
      "Undo maps nested template changes back to their original source",
    );
    await page
      .getByRole("button", { name: "Collapse templates", exact: true })
      .click();
    await page.locator(".template-include-link").first().click();
    await page.waitForSelector(".source-expansion-bar");
    check(
      (await source()).includes("Included inline draft"),
      "Collapse and re-expand retains the upstream draft",
    );
    await page
      .getByRole("button", { name: "Save source", exact: true })
      .click();
    await page.waitForFunction(
      () =>
        !document
          .querySelector(".expanded-source-name")
          .textContent.includes("Unsaved"),
    );
    check(
      fs.readFileSync(path.join(project, "templates/shared.md"), "utf8") ===
        fragmentDraft,
      "Saving expanded source writes the upstream template file",
    );
    await page
      .getByRole("button", { name: "Collapse templates", exact: true })
      .click();
    const beforeRepeatedInclude = await source();
    await edit(beforeRepeatedInclude + '\n{% include "shared.md" %}\n');
    await page.evaluate(async () => {
      const editor = monaco.editor.getEditors()[0];
      const find = (last) => {
        const lines = editor.getValue().split("\n");
        const indices = lines
          .map((line, index) =>
            line.includes('include "shared.md"') ? index + 1 : 0,
          )
          .filter(Boolean);
        editor.setPosition({
          lineNumber: last ? indices.at(-1) : indices[0],
          column: 1,
        });
      };
      find(false);
      await editor.getAction("md-doc.edit-include").run();
      find(true);
      await editor.getAction("md-doc.edit-include").run();
      const model = editor.getModel(),
        start = model.getValue().indexOf("Included inline draft");
      const from = model.getPositionAt(start),
        to = model.getPositionAt(start + "Included inline draft".length);
      editor.pushUndoStop();
      editor.executeEdits("repeated-test", [
        {
          range: new monaco.Range(
            from.lineNumber,
            from.column,
            to.lineNumber,
            to.column,
          ),
          text: "Mirrored draft",
        },
      ]);
      editor.pushUndoStop();
    });
    check(
      (await source()).split("Mirrored draft").length === 3,
      "Editing a shared template updates both expanded occurrences",
    );
    await page.evaluate(() =>
      monaco.editor.getEditors()[0].trigger("repeated-test", "undo", null),
    );
    check(
      (await source()).split("Included inline draft").length === 3 &&
        !(await source()).includes("Mirrored draft"),
      "Undo restores both occurrences without duplicating source edits",
    );
    await page.evaluate(() =>
      monaco.editor.getEditors()[0].trigger("repeated-test", "redo", null),
    );
    check(
      (await source()).split("Mirrored draft").length === 3,
      "Redo restores both shared-template occurrences",
    );
    await page.evaluate(() =>
      monaco.editor.getEditors()[0].trigger("repeated-test", "undo", null),
    );
    await page
      .getByRole("button", { name: "Collapse templates", exact: true })
      .click();
    await edit(beforeRepeatedInclude);
    await page.evaluate(async () => {
      const editor = monaco.editor.getEditors()[0];
      const line =
        editor
          .getValue()
          .split("\n")
          .findIndex((line) => line.includes('include "shared.md"')) + 1;
      editor.setPosition({ lineNumber: line, column: 1 });
      await editor.getAction("md-doc.edit-include").run();
    });
    await page.locator("#md-doc-save-btn").click();
    await page.waitForFunction(
      () => document.querySelector("#md-doc-save-btn").disabled,
    );
    check(
      fs.readFileSync(path.join(workspace, "doc.md"), "utf8") ===
        beforeRepeatedInclude &&
        fs.readFileSync(path.join(project, "templates/shared.md"), "utf8") ===
          fragmentDraft,
      "Main Save writes original source files rather than the expanded editor text",
    );
    await page.locator("#auto-preview").evaluate((node) => node.click());
    jobRequests.length = 0;
    page.on("request", recordPreview);
    await page.evaluate(() => {
      const editor = monaco.editor.getEditors()[0],
        model = editor.getModel();
      const start = model.getValue().indexOf("Included inline draft");
      const from = model.getPositionAt(start),
        to = model.getPositionAt(start + "Included inline draft".length);
      editor.pushUndoStop();
      editor.executeEdits("paused-outline", [
        {
          range: new monaco.Range(
            from.lineNumber,
            from.column,
            to.lineNumber,
            to.column,
          ),
          text: "Paused outline draft",
        },
      ]);
      editor.pushUndoStop();
    });
    await page
      .getByRole("button", { name: "Paused outline draft", exact: true })
      .waitFor();
    check(
      jobRequests.length === 0,
      "The composed outline updates unsaved templates with PDF regeneration paused",
    );
    await page.evaluate(() =>
      monaco.editor.getEditors()[0].trigger("paused-outline", "undo", null),
    );
    page.off("request", recordPreview);
    await page.locator("#auto-preview").evaluate((node) => node.click());
    const beforeBoundaryEdit = await source();
    await page.evaluate(() => {
      const editor = monaco.editor.getEditors()[0],
        model = editor.getModel();
      const start = model.getValue().indexOf('{% include "shared.md"'),
        end = model.getValue().indexOf("Included inline draft") + 5;
      const from = model.getPositionAt(start),
        to = model.getPositionAt(end);
      editor.executeEdits("boundary-test", [
        {
          range: new monaco.Range(
            from.lineNumber,
            from.column,
            to.lineNumber,
            to.column,
          ),
          text: "",
        },
      ]);
    });
    check(
      (await source()) === beforeBoundaryEdit,
      "A deletion spanning source files cannot corrupt the parent or its template",
    );
    await page
      .getByRole("button", { name: "Collapse templates", exact: true })
      .click();
    await page.locator('[data-nav="files"]').click();
    await page.keyboard.press("Control+k");
    await page.locator("#command-query").fill("> Studio settings");
    await page.keyboard.press("Enter");
    check(
      (await page.locator("#settings-delay").inputValue()) === "1500",
      "Default preview delay is 1.5 seconds",
    );
    await page.locator("#settings-delay").selectOption("3000");
    await page.getByRole("button", { name: "Done", exact: true }).click();
    check(
      await page.evaluate(() =>
        Object.keys(localStorage).some(
          (key) =>
            key.endsWith(":previewDelay") &&
            localStorage.getItem(key) === "3000",
        ),
      ),
      "Preview delay preference persists for the workspace",
    );
    await page.keyboard.press("Control+k");
    await page.locator("#command-query").fill("> Studio settings");
    await page.keyboard.press("Enter");
    check(
      (await page.locator("#settings-delay").inputValue()) === "3000",
      "Settings restores the chosen preview delay",
    );
    await page.locator("#settings-delay").selectOption("1500");
    await page.getByRole("button", { name: "Done", exact: true }).click();
    await page.waitForFunction(
      () => document.querySelector("#preview-status").textContent === "Current",
    );
    // A separate PDF.js window follows the editor's unsaved output.
    const popupPromise = page.waitForEvent("popup");
    await page
      .getByRole("button", { name: "Pop out preview", exact: true })
      .click();
    const popup = await popupPromise;
    popup.on("pageerror", (error) => errors.push(error.message));
    await popup.waitForFunction(() =>
      document
        .querySelector(".pdfViewer .textLayer")
        ?.textContent.includes("Snapshot UnsavedBrand"),
    );
    check(
      (await popup.locator(".page canvas").count()) > 0,
      "Pop-out renders the final PDF",
    );
    const priorPages = page.context().pages().length;
    await page
      .getByRole("button", { name: "Pop out preview", exact: true })
      .click();
    check(
      page.context().pages().length === priorPages,
      "Pop-out button reuses its open window",
    );
    await page.locator('[data-path="doc.md"]').click();
    const popoutSource = await source();
    await edit(
      popoutSource.replace("# Snapshot", "# Live detached preview update"),
    );
    await popup.waitForFunction(() =>
      [...document.querySelectorAll(".textLayer")].some((n) =>
        n.textContent.includes("Live detached preview update"),
      ),
    );
    check(
      (await popup.locator("#preview-status").textContent()) === "Current",
      "Pop-out receives unsaved PDF updates",
    );
    await popup.locator("#pdf-zoom").selectOption("page-fit");
    await popup.setViewportSize({ width: 900, height: 700 });
    check(
      await popup.locator("#pdf-container").isVisible(),
      "Pop-out supports independent zoom and resizing",
    );
    const popupDownload = popup.waitForEvent("download");
    await popup
      .getByRole("button", { name: "Download PDF", exact: true })
      .click();
    check(
      fs
        .readFileSync(await (await popupDownload).path())
        .subarray(0, 4)
        .toString() === "%PDF",
      "Pop-out downloads the displayed PDF",
    );
    await edit(popoutSource);
    await page.waitForFunction(
      () => document.querySelector("#preview-status").textContent === "Current",
    );
    await page.locator('[data-path="second.md"]').click();
    await popup.waitForFunction(() =>
      document
        .querySelector(".pdfViewer .textLayer")
        ?.textContent.includes("Second document"),
    );
    check(
      (await popup.locator("#preview-document").textContent()) === "second.md",
      "Pop-out follows the selected document",
    );
    await page.locator('[data-path="doc.md"]').click();
    await popup.waitForFunction(() =>
      document
        .querySelector(".pdfViewer .textLayer")
        ?.textContent.includes("Snapshot UnsavedBrand"),
    );
    await page
      .getByRole("button", { name: "Switch appearance", exact: true })
      .click();
    await popup.waitForFunction(
      () => document.documentElement.dataset.theme === "dark",
    );
    check(
      (await popup.locator("html").getAttribute("data-theme")) ===
        (await page.locator("html").getAttribute("data-theme")),
      "Pop-out follows editor appearance",
    );
    await page
      .getByRole("button", { name: "Switch appearance", exact: true })
      .click();
    await popup.close();
    const reopenPromise = page.waitForEvent("popup");
    await page
      .getByRole("button", { name: "Pop out preview", exact: true })
      .click();
    const reopened = await reopenPromise;
    await reopened.waitForSelector(".page canvas");
    check(
      (await reopened.locator("#pdf-total").textContent()) === "3",
      "Closed pop-out can be reopened",
    );
    await reopened.close();
    // Viewer controls, thumbnails, zoom and search.
    await page
      .getByRole("button", { name: "Page thumbnails", exact: true })
      .click();
    await page.waitForSelector(".thumbnail canvas");
    check((await page.locator(".thumbnail").count()) === 3, "Thumbnails");
    await page.locator("#pdf-zoom").selectOption("page-fit");
    await page.locator("#pdf-page").fill("2");
    await page.locator("#pdf-page").press("Enter");
    await page.locator("#pdf-page").blur();
    await page.getByRole("button", { name: "Search PDF", exact: true }).click();
    await page.locator("#pdf-find-query").fill("UnsavedBrand");
    await page.waitForFunction(() =>
      /\/\s*[1-9]/.test(document.querySelector("#pdf-find-count").textContent),
    );
    check(
      (await page.locator("#pdf-find-count").textContent()).includes("1"),
      "PDF find",
    );
    await page
      .getByRole("button", { name: "Close PDF search", exact: true })
      .click();
    // Visual round trip leaves template syntax intact and edits supported paragraphs.
    await page.locator('[data-path="doc.md"]').click();
    await page.getByRole("button", { name: "Write", exact: true }).click();
    check(
      (await page.locator(".protected-block").count()) >= 2,
      "Template and YAML syntax are protected",
    );
    const paragraph = page
      .locator("[contenteditable=true]")
      .filter({ hasText: "Unsaved source paragraph." });
    await paragraph.fill("Edited in visual mode.");
    await page.getByRole("button", { name: "Source", exact: true }).click();
    check(
      (await source()).includes('{% include "shared.md" %}'),
      "Visual mode preserves includes",
    );
    check(
      (await source()).includes("Edited in visual mode."),
      "Visual paragraph changes source",
    );
    // External edits must produce a conflict rather than silently overwrite disk.
    fs.writeFileSync(path.join(workspace, "doc.md"), "# External change\n");
    await page.locator("#md-doc-save-btn").click();
    await page.getByRole("heading", { name: "Review file changes" }).waitFor();
    check(
      fs.readFileSync(path.join(workspace, "doc.md"), "utf8") ===
        "# External change\n",
      "Conflict keeps disk intact",
    );
    await page
      .getByRole("button", { name: "Save my draft", exact: true })
      .click();
    await page.waitForFunction(
      () => !document.querySelector("#form-dialog").open,
    );
    check(
      fs
        .readFileSync(path.join(workspace, "doc.md"), "utf8")
        .includes("Edited in visual mode."),
      "Explicit conflict resolution saves draft",
    );
    // Source control is scoped to workspace and renders real diff.
    await page
      .getByRole("button", { name: "Source control", exact: true })
      .click();
    await page.locator(".git-file").first().waitFor();
    await page
      .locator(".git-file")
      .getByRole("button", { name: "doc.md", exact: true })
      .click();
    await page.getByRole("heading", { name: "Diff: doc.md" }).waitFor();
    check(
      (await page.locator(".git-diff").textContent()).includes(
        "Edited in visual mode.",
      ),
      "Git diff displays current changes",
    );
    await page.getByRole("button", { name: "Close", exact: true }).click();
    await page
      .getByRole("button", { name: "Stage doc.md", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Unstage doc.md", exact: true })
      .waitFor();
    check(
      git("diff", "--cached", "--name-only").includes("documents/doc.md"),
      "Git stage action",
    );
    // Styling changes are rendered from unsaved dependency buffers too.
    await page
      .getByRole("button", { name: "Document properties", exact: true })
      .click();
    await page.getByRole("button", { name: "Theme", exact: true }).click();
    await page
      .getByRole("button", {
        name: path.join(project, "_theme.css"),
        exact: true,
      })
      .click();
    await page.waitForFunction(
      () => monaco.editor.getEditors()[0].getModel().getLanguageId() === "css",
    );
    const diskCss = fs.readFileSync(path.join(project, "_theme.css"), "utf8");
    await edit(diskCss + "\nbody { color: #cc2244; }\n");
    await page
      .getByRole("button", { name: "Close inspector", exact: true })
      .click();
    await page.waitForFunction(
      () => document.querySelector("#preview-status").textContent === "Current",
      null,
      { timeout: 30000 },
    );
    check(
      fs.readFileSync(path.join(project, "_theme.css"), "utf8") === diskCss,
      "Unsaved CSS preview preserves source theme",
    );
    // Responsive layout and appearance without script or network failures.
    await page
      .getByRole("button", { name: "Switch appearance", exact: true })
      .click();
    check(
      (await page.locator("html").getAttribute("data-theme")) === "dark",
      "Dark appearance",
    );
    await page.setViewportSize({ width: 760, height: 900 });
    await page.getByRole("button", { name: "Commands", exact: true }).count();
    await page.keyboard.press("Control+k");
    await page.locator("#command-query").fill("> Change layout");
    await page.keyboard.press("Enter");
    await page
      .getByRole("button", { name: "Preview only", exact: false })
      .click();
    check(
      await page.locator("#preview-pane").isVisible(),
      "Narrow preview-only layout",
    );
    await page.screenshot({
      path: path.join(os.tmpdir(), "md-doc-studio-mobile.png"),
    });
    await page.setViewportSize({ width: 1480, height: 980 });
    await page
      .getByRole("button", { name: "Change layout", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Side by side", exact: false })
      .click();
    for (const name of [
      "Preview only",
      "Source only",
      "Stacked",
      "Side by side",
    ]) {
      await page.keyboard.press("Control+k");
      await page.locator("#command-query").fill("> Change layout");
      await page.keyboard.press("Enter");
      await page.getByRole("button", { name, exact: false }).click();
      if (
        !(await page
          .locator("#workbench")
          .evaluate((n) => n.classList.contains("nav-hidden")))
      )
        await page
          .getByRole("button", { name: "Hide file sidebar", exact: true })
          .click();
      const pane = name === "Preview only" ? "#preview-pane" : "#editor-pane";
      check(
        Math.abs((await page.locator(pane).boundingBox()).x - 46) < 1,
        "Hidden sidebar reclaims navigation space in " + name,
      );
    }
    await page.locator('[data-nav="files"]').click();
    await page.screenshot({
      path: path.join(os.tmpdir(), "md-doc-studio-final.png"),
    });
    check(
      external.length === 0,
      "No external browser requests: " + external.join(", "),
    );
    check(
      errors.length === 0,
      "No uncaught browser errors: " + errors.join(", "),
    );
    const broken = await browser.newPage();
    await broken.route(
      "**/static/vendor/pdfjs-6.4.299/legacy/build/pdf.min.mjs",
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "text/plain",
          body: "PDF module served with an incorrect MIME type",
        }),
    );
    await broken.goto(origin + "/?file=second.md");
    await broken.waitForFunction(
      () =>
        document.querySelector("#preview-status").textContent ===
        "Viewer unavailable",
      null,
      { timeout: 30000 },
    );
    check(
      (await broken.locator("#diagnostics-content").textContent()).includes(
        "pdf.min.mjs was served as text/plain",
      ),
      "A nested module failure identifies the exact asset and response type",
    );
    const generated = await broken.request.get(
      new URL(
        await broken.locator("#preview-recovery-link").getAttribute("href"),
        origin,
      ).href,
    );
    check(
      (await generated.body()).subarray(0, 4).toString() === "%PDF",
      "The generated PDF remains accessible when its browser viewer cannot load",
    );
    await broken.close();
    console.log(
      `${checks} production studio browser checks passed (real Monaco, PDF, offline assets, resizing, recovery, conflicts, visual editing, Git)`,
    );
  } catch (error) {
    if (testPage) {
      console.error(
        "BROWSER STATE:",
        await testPage.evaluate(() => ({
          status: document.querySelector("#preview-status").textContent,
          diagnostics: document.querySelector("#diagnostics-content")
            .textContent,
          search: document.querySelector("#pdf-find-count").textContent,
          findState: window.studioTestViewer?.findController.state,
          pages: window.studioTestViewer?.findController._pageContents,
        })),
      );
      await testPage.screenshot({
        path: path.join(os.tmpdir(), "md-doc-studio-failure.png"),
      });
    }
    console.error("SERVER LOG:", output.slice(-1500));
    throw error;
  } finally {
    if (browser) await browser.close();
    server.kill();
    await new Promise((resolve) =>
      server.exitCode !== null ? resolve() : server.once("exit", resolve),
    );
    fs.rmSync(project, { recursive: true, force: true });
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
