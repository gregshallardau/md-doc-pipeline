/* The editor owns rendering; this window displays the same finished artifact. */
const $ = (id) => document.getElementById(id);
let viewer,
  initialize,
  latest,
  loadedUrl,
  loadedPath,
  sequence = 0;
const send = (type) => window.opener?.postMessage({ type }, location.origin);
function fail(error) {
  const status = $("preview-status") || $("startup");
  status.textContent = "Preview unavailable: " + error.message;
  $("preview-loading")?.setAttribute("hidden", "");
}
async function setup(markup) {
  const parsed = new DOMParser().parseFromString(markup, "text/html");
  const pane = parsed.getElementById("preview-pane");
  if (!pane) throw new Error("The editor did not provide a preview.");
  document.body.replaceChildren(pane);
  pane.querySelector(".preview-footer").remove();
  const actions = pane.querySelector(".preview-layout-actions");
  actions.replaceChildren();
  for (const [label, action] of [
    ["Download PDF", download],
    ["Back to editor", () => window.opener?.focus()],
  ]) {
    const button = document.createElement("button");
    button.className = "button";
    button.textContent = label;
    button.onclick = action;
    actions.append(button);
  }
  pane.querySelectorAll('[data-action="pdf-find"]').forEach((button) => {
    button.onclick = () => {
      $("pdf-find-bar").hidden = !$("pdf-find-bar").hidden;
      if (!$("pdf-find-bar").hidden) $("pdf-find-query").focus();
      else viewer?.closeFind();
    };
  });
  pane.querySelector('[data-action="refresh-preview"]').onclick = () =>
    send("md-doc-preview-refresh");
  $("preview-status").removeAttribute("data-action");
  const module = await import("./viewer.js");
  viewer = new module.DocumentViewer(fail);
}
function download() {
  if (!latest?.artifact) return;
  const link = document.createElement("a");
  link.href =
    latest.artifact.url +
    (latest.artifact.url.includes("?") ? "&" : "?") +
    "download=true";
  link.download = latest.artifact.filename;
  link.click();
}
async function update(data) {
  const token = ++sequence;
  if (!initialize) {
    if (!data.markup) return;
    initialize = setup(data.markup);
  }
  await initialize;
  if (token !== sequence) return;
  document.documentElement.dataset.theme = data.theme;
  document.title = (data.path || "Output preview") + " · md-doc preview";
  $("preview-document").textContent = data.path || "No document selected";
  $("preview-status").textContent = data.status;
  $("preview-status").className = data.kind;
  $("preview-loading").hidden = !data.kind.includes("updating");
  if (!data.artifact) {
    viewer.invalidate();
    loadedUrl = loadedPath = null;
    $("preview-empty").hidden = false;
    $("preview-empty").querySelector("h2").textContent =
      "Choose a document in the editor";
    return;
  }
  if (data.artifact.url !== loadedUrl) {
    await viewer.load(data.artifact, loadedPath === data.path);
    if (token !== sequence) return;
    loadedUrl = data.artifact.url;
    loadedPath = data.path;
  }
}
window.addEventListener("message", (event) => {
  if (
    event.origin !== location.origin ||
    event.source !== window.opener ||
    event.data?.type !== "md-doc-preview"
  )
    return;
  latest = event.data;
  update(latest).catch(fail);
});
if (window.opener) send("md-doc-preview-ready");
else
  $("startup").textContent =
    "Open this preview using Pop out preview in the editor.";
setInterval(() => {
  if (window.opener?.closed && $("preview-status")) {
    $("preview-status").textContent = "Editor closed · last rendered output";
    document.querySelector('[data-action="refresh-preview"]').disabled = true;
  }
}, 1000);
