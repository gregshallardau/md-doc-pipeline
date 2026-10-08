/* Filament client regressions. The standalone studio uses studio.cjs. */
const { chromium } = require('playwright');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
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
  const browser = await chromium.launch({headless:true,...(process.env.MD_DOC_TEST_BROWSER?{executablePath:process.env.MD_DOC_TEST_BROWSER}:{})});
  try {
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
