/* Real packaged assets, server and Monaco, with all external requests forbidden. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const {spawn} = require('node:child_process');
const root = path.resolve(__dirname, '../..');
(async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'md-doc-offline-'));
  fs.mkdirSync(path.join(directory, '.git'));
  fs.writeFileSync(path.join(directory, 'doc.md'), '# Offline document\nHello.');
  const listener = net.createServer();
  await new Promise(resolve => listener.listen(0, '127.0.0.1', resolve));
  const port = listener.address().port;
  await new Promise(resolve => listener.close(resolve));
  const origin = `http://127.0.0.1:${port}`;
  const server = spawn(process.env.MD_DOC_TEST_PYTHON || path.join(root, '.venv/bin/python'),
    ['-m', 'md_doc_web_editor.cli', 'serve', directory, '--no-browser', '--port', String(port)],
    {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
  let output = '';
  server.stdout.on('data', data => output += data);
  server.stderr.on('data', data => output += data);
  let browser;
  try {
    let ready = false;
    for (let i = 0; i < 100; i++) {
      try { if ((await fetch(origin)).ok) { ready = true; break; } } catch {}
      if (server.exitCode !== null) throw new Error(output);
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert(ready, output);
    browser = await chromium.launch({headless: true});
    const context = await browser.newContext({serviceWorkers: 'block'});
    const external = [];
    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.origin !== origin && !['data:', 'blob:', 'about:'].includes(url.protocol)) {
        external.push(url.href);
        return route.abort();
      }
      return route.continue();
    });
    const page = await context.newPage();
    const response = await page.goto(origin);
    assert.match(response.headers()['content-security-policy'], /connect-src 'self'/);
    await page.locator('[data-path="doc.md"]').click();
    await page.waitForFunction(() => window.monaco?.editor.getModels()[0]?.getValue().includes('Offline document'));
    assert.equal(await page.locator('.md-doc-local-editor').count(), 0);
    await page.frameLocator('#md-doc-preview iframe').getByRole('heading', {name: 'Offline document'}).waitFor();
    // CSS imports, images and refresh/navigation supplied by a document cannot go online.
    await page.evaluate(() => monaco.editor.getModels()[0].setValue(
      '# Still local\n<img src="https://example.invalid/image.png">'
      + '<meta http-equiv="refresh" content="0;url=https://example.invalid/refresh">'
      + '<a href="https://example.invalid/link">external link</a>'
      + '<style>@import "https://example.invalid/theme.css";</style>'));
    await page.frameLocator('#md-doc-preview iframe').getByRole('heading', {name: 'Still local'}).waitFor();
    assert.equal(await page.frameLocator('#md-doc-preview iframe').locator('a').getAttribute('href'), null);
    await page.locator('#md-doc-save-btn').click();
    await page.waitForFunction(() => document.querySelector('#md-doc-save-btn').textContent === 'Saved ✓');
    assert.match(fs.readFileSync(path.join(directory, 'doc.md'), 'utf8'), /Still local/);
    for (const format of ['pdf', 'docx']) {
      const result = await fetch(origin + '/api/build', {method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({path:'doc.md', format})});
      assert.equal(result.status, 200, await result.clone().text());
      const artifact = await result.json();
      assert.equal((await fetch(origin + '/api/build/' + artifact.token)).status, 200);
    }
    assert.deepEqual(external, []);
    console.log('Offline server, real Monaco, preview, save and PDF/DOCX exports passed with external browser requests blocked');
  } finally {
    if (browser) await browser.close();
    server.kill();
    await new Promise(resolve => server.exitCode !== null ? resolve() : server.once('exit', resolve));
    fs.rmSync(directory, {recursive: true, force: true});
  }
})().catch(error => {console.error(error); process.exit(1);});
