/* Browser regressions with deterministic Monaco/API adapters; real Chromium DOM and sandbox. */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const standalone = path.join(root, 'md-doc-web-editor/md_doc_web_editor/static');
const filament = path.join(root, 'filament-md-doc/resources/js/editor.js');
const adapter = `
window.marked = {parse: s => s};
window.monaco = { KeyMod: {CtrlCmd: 1}, KeyCode: {KeyS: 1}, editor: {
  setModelLanguage() {}, create(container, options) {
    let value = options.value, change = () => {};
    window.testEditor = {
      getValue: () => value, setValue(v) { value=v; change(); },
      getModel: () => ({}), onDidChangeModelContent(fn) { change=fn; },
      addCommand() {}, updateOptions() {}, dispose() {}
    };
    return window.testEditor;
  }
}};
window.require = (_, callback) => callback();
window.confirm = () => window.allowDiscard ?? false;
window.alert = message => { window.lastAlert = message; };
`;
let checks = 0;
async function check(value, expected) { assert.deepEqual(await value, expected); checks++; }
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage();
    const files = { 'a.md': 'original A', 'b.md': 'original B' };
    const builds = [];
    let releaseSave, saveStarted;
    let delaySave = false;
    await page.route('http://editor.test/**', async route => {
      const req = route.request();
      const url = new URL(req.url());
      let data = {};
      if (url.pathname === '/') {
        const html = fs.readFileSync(path.join(standalone,'index.html'),'utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '').replace(/<link\b[^>]*>/gi, '');
        return route.fulfill({contentType:'text/html', body:html});
      }
      if (url.pathname === '/api/tree') data = {tree:Object.keys(files).map(name=>({name,path:name,type:'md'}))};
      else if (url.pathname === '/api/file' && req.method() === 'GET') data = {path:url.searchParams.get('path'),type:'md',content:files[url.searchParams.get('path')]};
      else if (url.pathname === '/api/file') {
        const body = req.postDataJSON();
        if (delaySave) { saveStarted?.(); await new Promise(resolve=>releaseSave=resolve); }
        files[body.path] = body.content;
        data = {ok:true};
      } else if (url.pathname === '/api/config') data = {merged:{},layers:[]};
      else if (url.pathname === '/api/css') data = {css:'body { background: red }',source:null};
      else if (url.pathname === '/api/includes') data = {includes:[]};
      else if (url.pathname === '/api/build') { builds.push(req.postDataJSON()); data={token:'test',filename:'a.docx'}; }
      await route.fulfill({json:data});
    });
    await page.goto('http://editor.test/');
    await page.addScriptTag({content:adapter});
    await page.addScriptTag({path:path.join(standalone,'editor.js')});
    await page.evaluate(()=>document.dispatchEvent(new Event('DOMContentLoaded')));
    await page.locator('[data-path="a.md"]').click();
    await page.waitForFunction(()=>window.testEditor?.getValue() === 'original A');
    await page.evaluate(()=>testEditor.setValue('unsaved A'));
    await page.locator('[data-path="b.md"]').click();
    await check(page.locator('#md-doc-filename').textContent(), 'a.md');
    await check(page.evaluate(()=>testEditor.getValue()), 'unsaved A');
    await check(page.evaluate(()=>{
      const event=new Event('beforeunload',{cancelable:true}); window.dispatchEvent(event); return event.defaultPrevented;
    }), true);
    await page.locator('#md-doc-save-btn').click();
    await page.waitForFunction(()=>document.querySelector('#md-doc-save-btn').textContent === 'Saved ✓');
    await check(Promise.resolve(files['a.md']), 'unsaved A');
    await check(page.evaluate(()=>{
      const event=new Event('beforeunload',{cancelable:true}); window.dispatchEvent(event); return event.defaultPrevented;
    }), false);
    // A switch during save/build must not change the requested build path or replace the new preview.
    await page.evaluate(()=>{ window.allowDiscard=true; testEditor.setValue('build snapshot'); });
    delaySave = true;
    const started = new Promise(resolve=>saveStarted=resolve);
    await page.locator('#md-doc-build-docx-btn').click();
    await started;
    await page.locator('[data-path="b.md"]').click();
    await page.waitForFunction(()=>testEditor.getValue() === 'original B');
    releaseSave(); delaySave = false;
    await page.waitForFunction(()=>document.querySelector('#md-doc-build-docx-btn').textContent === 'Build DOCX');
    await check(Promise.resolve(builds[0]), {path:'a.md',format:'docx'});
    await check(Promise.resolve(files['a.md']), 'build snapshot');
    await check(page.locator('#md-doc-filename').textContent(), 'b.md');
    // Untrusted markup is only mounted in an opaque, script-disabled iframe.
    await page.evaluate(()=>testEditor.setValue('<img src="x" onerror="parent.pwned=1"><script>parent.pwned=1<\/script><p>safe text</p>'));
    await page.waitForFunction(()=>document.querySelector('#md-doc-preview iframe')?.srcdoc.includes('safe text'));
    await check(page.locator('#md-doc-preview iframe').getAttribute('sandbox'), '');
    await check(page.evaluate(()=>window.pwned ?? null), null);
    await check(page.evaluate(()=>getComputedStyle(document.body).backgroundColor), 'rgba(0, 0, 0, 0)');
    await check(page.locator('#md-doc-preview > img').count(), 0);

    // Run the Filament client event lifecycle and preview in a second page.
    const panel = await browser.newPage();
    await panel.setContent('<div id="md-doc-monaco"></div><div id="md-doc-preview"></div>');
    await panel.addScriptTag({content:adapter + `
      window.handlers={}; window.events=[];
      window.Livewire={on:(name,fn)=>handlers[name]=fn,dispatch:(name,detail)=>events.push({name,detail})};
      window.mdDocInitialContent='first'; window.mdDocPath='first.md'; window.mdDocFileType='md';
    `});
    await panel.addScriptTag({path:filament});
    await panel.evaluate(()=>{
      document.dispatchEvent(new Event('livewire:init'));
      mdDocEditorComponent({}).init();
      testEditor.setValue('pending old file edit');
      handlers['file-loaded']({path:'second.md',content:'second document',fileType:'md',mergedConfig:{},resolvedCss:'body{background:red}',lockKey:null,isReadOnly:false});
    });
    await check(panel.evaluate(()=>window.mdDocPath), 'second.md');
    await check(panel.evaluate(()=>testEditor.getValue()), 'second document');
    await panel.waitForFunction(()=>events.length > 0);
    await check(panel.evaluate(()=>events.every(e=>e.detail.path === 'second.md')), true);
    await check(panel.locator('#md-doc-preview iframe').getAttribute('sandbox'), '');
    await check(panel.evaluate(()=>getComputedStyle(document.body).backgroundColor), 'rgba(0, 0, 0, 0)');
    console.log(`${checks} browser regression checks passed`);
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1)});
