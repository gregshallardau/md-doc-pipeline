/* Locally bundled PDF.js. Document JavaScript and external links are disabled. */
import * as pdfjs from "./vendor/pdfjs-6.4.299/legacy/build/pdf.min.mjs";
import {indexPdfText, sourceAnchors, locateSourceLine} from "./scroll-sync.js";
globalThis.pdfjsLib = pdfjs;
const components = await import("./vendor/pdfjs-6.4.299/web/pdf_viewer.mjs");
pdfjs.GlobalWorkerOptions.workerSrc =
  "/static/vendor/pdfjs-6.4.299/legacy/build/pdf.worker.min.mjs";
const $ = (id) => document.getElementById(id);
const base = "/static/vendor/pdfjs-6.4.299/";
export class DocumentViewer {
  constructor(onError) {
    this.onError = onError;
    this.sequence = 0;
    this.sourceSyncSequence = 0;
    this.eventBus = new components.EventBus();
    this.linkService = new components.PDFLinkService({
      eventBus: this.eventBus,
    });
    this.linkService.externalLinkEnabled = false;
    this.findController = new components.PDFFindController({
      eventBus: this.eventBus,
      linkService: this.linkService,
    });
    this.viewerAbort = new AbortController();
    this.viewer = new components.PDFViewer({
      container: $("pdf-container"),
      viewer: $("pdf-viewer"),
      eventBus: this.eventBus,
      linkService: this.linkService,
      findController: this.findController,
      annotationMode: pdfjs.AnnotationMode.ENABLE,
      enableAutoLinking: false,
      imageResourcesPath: base + "web/images/",
      maxCanvasPixels: 8 * 1024 * 1024,
      abortSignal: this.viewerAbort.signal,
    });
    this.linkService.setViewer(this.viewer);
    this.eventBus.on("pagesinit", () => {
      this.setPageView();
      this.viewer.currentScaleValue = $("pdf-zoom").value;
      if (this.pendingPage)
        this.viewer.currentPageNumber = Math.min(
          this.pendingPage,
          this.document.numPages,
        );
      this.pendingPage = null;
      this.viewer.update();
    });
    this.eventBus.on("pagechanging", ({ pageNumber }) => {
      $("pdf-page").value = pageNumber;
      $("pdf-thumbnails")
        .querySelectorAll(".thumbnail")
        .forEach((b) =>
          b.classList.toggle("active", Number(b.dataset.page) === pageNumber),
        );
      this.scheduleFit();
    });
    // Page views initially inherit the first page's geometry. Refit once PDF.js
    // has loaded the actual dimensions of the remaining pages as well.
    this.eventBus.on("pagesloaded", () => this.scheduleFit());
    this.eventBus.on("updatefindmatchescount", ({ matchesCount }) => {
      $("pdf-find-count").textContent =
        `${matchesCount.current} / ${matchesCount.total}`;
    });
    this.eventBus.on("updatefindcontrolstate", ({ state, matchesCount }) => {
      if (state === 1) $("pdf-find-count").textContent = "No matches";
      else if (matchesCount?.total)
        $("pdf-find-count").textContent =
          `${matchesCount.current} / ${matchesCount.total}`;
    });
    $("pdf-prev").onclick = () => this.go(this.viewer.currentPageNumber - 1);
    $("pdf-next").onclick = () => this.go(this.viewer.currentPageNumber + 1);
    $("pdf-page").onchange = () => this.go(Number($("pdf-page").value));
    $("pdf-page-view").onchange = () => this.setPageView();
    $("pdf-zoom").onchange = () => {
      if (this.document) this.viewer.currentScaleValue = $("pdf-zoom").value;
    };
    $("thumbnails-toggle").onclick = () => {
      $("pdf-thumbnails").hidden = !$("pdf-thumbnails").hidden;
      if (!$("pdf-thumbnails").hidden) this.thumbnails();
      this.resize();
    };
    $("pdf-find-query").oninput = () => this.find();
    $("pdf-find-query").onkeydown = (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        this.find(true, event.shiftKey);
      }
    };
    $("pdf-find-next").onclick = () => this.find(true);
    new ResizeObserver(() => this.resize()).observe($("pdf-container"));
  }
  async load(artifact, sameDocument = false) {
    this.sourceSyncSequence = (this.sourceSyncSequence || 0) + 1;
    this.textIndex = null;
    this.sourceMap = null;
    this.clearPreviewPages();
    const sequence = ++this.sequence;
    this.loading?.destroy().catch(() => {});
    const task = pdfjs.getDocument({
      url: artifact.url,
      cMapUrl: base + "cmaps/",
      cMapPacked: true,
      standardFontDataUrl: base + "standard_fonts/",
      wasmUrl: base + "wasm/",
      isEvalSupported: false,
      enableXfa: false,
      disableAutoFetch: true,
      disableStream: true,
    });
    this.loading = task;
    let doc;
    try {
      doc = await task.promise;
    } catch (error) {
      if (sequence === this.sequence) throw error;
      return;
    }
    if (sequence !== this.sequence) {
      await task.destroy();
      return;
    }
    const oldTask = this.documentTask;
    this.documentTask = task;
    this.loading = null;
    this.pendingPage = sameDocument ? this.viewer.currentPageNumber : 1;
    this.document = doc;
    this.artifact = artifact;
    this.viewer.setDocument(doc);
    this.linkService.setDocument(doc);
    $("pdf-total").textContent = doc.numPages;
    $("pdf-page").max = doc.numPages;
    $("preview-empty").hidden = true;
    this.thumbnailObserver?.disconnect();
    $("pdf-thumbnails").replaceChildren();
    if (!$("pdf-thumbnails").hidden) this.thumbnails();
    if (oldTask) await oldTask.destroy();
  }
  clearPreviewPages() {
    this.previewSequence = (this.previewSequence || 0) + 1;
    this.previewUrls = new Set();
    $("pdf-viewer").querySelectorAll(".preview-page-update").forEach(node => node.remove());
    $("pdf-viewer").querySelectorAll(".preview-provisional").forEach(node => {
      node.classList.remove("preview-provisional");
      delete node.dataset.previewRevision;
    });
  }
  async showPreviewPages(pages, revision) {
    if (!this.document) return;
    this.previewUrls ||= new Set();
    const sequence = this.sequence;
    const previewSequence = this.previewSequence || 0;
    for (const page of pages || []) {
      if (page.revision !== revision || this.previewUrls.has(page.url)) continue;
      const host = this.viewer.getPageView(page.page - 1)?.div;
      if (!host) continue;
      this.previewUrls.add(page.url);
      const task = pdfjs.getDocument({
        url: page.url, cMapUrl: base + "cmaps/", cMapPacked: true,
        standardFontDataUrl: base + "standard_fonts/", wasmUrl: base + "wasm/",
        isEvalSupported: false, enableXfa: false,
      });
      try {
        const doc = await task.promise;
        const pdfPage = await doc.getPage(1);
        const intrinsic = pdfPage.getViewport({scale: 1});
        const scale = host.clientWidth / intrinsic.width;
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        const viewport = pdfPage.getViewport({scale: scale * ratio});
        const canvas = document.createElement("canvas");
        canvas.width = Math.ceil(viewport.width);
        canvas.height = Math.ceil(viewport.height);
        canvas.style.width = "100%";
        canvas.style.height = "100%";
        await pdfPage.render({canvasContext: canvas.getContext("2d"), viewport}).promise;
        if (sequence !== this.sequence || previewSequence !== (this.previewSequence || 0)) return;
        const overlay = document.createElement("div");
        overlay.className = "preview-page-update";
        overlay.title = "Updated page; page totals and references are provisional";
        overlay.append(canvas);
        host.querySelector(".preview-page-update")?.remove();
        host.append(overlay);
        host.classList.add("preview-provisional");
        host.dataset.previewRevision = revision;
      } catch (error) {
        this.previewUrls.delete(page.url);
        // A newer edit cancels the render that produced this provisional page
        // and deletes its files, so the fetch can legitimately 404. Only
        // report failures for a preview that is still current.
        const stale = sequence !== this.sequence || previewSequence !== (this.previewSequence || 0);
        if (!stale && error?.status !== 404) this.onError(error);
      } finally {
        await task.destroy();
      }
    }
  }
  invalidate() {
    this.sourceSyncSequence = (this.sourceSyncSequence || 0) + 1;
    this.clearPreviewPages();
    ++this.sequence;
    this.loading?.destroy().catch(() => {});
    this.loading = null;
  }
  go(page) {
    if (this.document)
      this.viewer.currentPageNumber = Math.max(
        1,
        Math.min(page, this.document.numPages),
      );
  }
  async scrollToSource(source, line) {
    if (!this.document) return;
    const document = this.document;
    const sequence = ++this.sourceSyncSequence;
    this.textIndex ||= indexPdfText(document).catch(error => {
      if (this.document === document) this.textIndex = null;
      throw error;
    });
    const index = await this.textIndex;
    if (sequence !== this.sourceSyncSequence || document !== this.document) return;
    if (this.sourceMap?.source !== source)
      this.sourceMap = {source, anchors: sourceAnchors(source, index)};
    const target = locateSourceLine(this.sourceMap.anchors, line);
    if (!target) return;
    const viewport = index.pages[target.page - 1];
    const [x, y] = viewport.convertToPdfPoint(0, target.top * viewport.height);
    this.viewer.scrollPageIntoView({pageNumber: target.page,
      destArray: [null, {name: "XYZ"}, x, y, null], allowNegativeOffset: false});
  }
  cancelSourceScroll() {
    this.sourceSyncSequence = (this.sourceSyncSequence || 0) + 1;
  }
  setPageView() {
    this.viewer.spreadMode = $("pdf-page-view").value === "spread"
      ? components.SpreadMode.ODD
      : components.SpreadMode.NONE;
    this.resize();
  }
  scheduleFit() {
    if (!this.document || !["page-width", "page-fit"].includes($("pdf-zoom").value))
      return;
    cancelAnimationFrame(this.fitFrame);
    // Let PDF.js finish updating its scroll location before changing the scale.
    this.fitFrame = requestAnimationFrame(() => {
      this.fitFrame = null;
      this.resize();
    });
  }
  resize() {
    if (this.document) {
      if (["page-width", "page-fit"].includes($("pdf-zoom").value))
        this.viewer.currentScaleValue = $("pdf-zoom").value;
      this.viewer.update();
    }
  }
  find(again = false, previous = false) {
    this.eventBus.dispatch("find", {
      type: again ? "again" : "",
      query: $("pdf-find-query").value,
      caseSensitive: false,
      entireWord: false,
      highlightAll: true,
      findPrevious: previous,
    });
  }
  closeFind() {
    this.eventBus.dispatch("findbarclose", {});
  }
  async thumbnails() {
    if (!this.document || $("pdf-thumbnails").childElementCount) return;
    const doc = this.document;
    const bookmarks = await doc.getOutline();
    if (doc !== this.document) return;
    if (bookmarks?.length) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "Bookmarks";
      details.className = "pdf-bookmarks";
      details.append(summary);
      const addBookmarks = (items, depth = 0) => {
        for (const item of items) {
          if (item.dest) {
            const button = document.createElement("button");
            button.textContent = item.title;
            button.title = item.title;
            button.style.paddingLeft = 4 + depth * 6 + "px";
            button.onclick = () => this.linkService.goToDestination(item.dest);
            details.append(button);
          }
          addBookmarks(item.items || [], depth + 1);
        }
      };
      addBookmarks(bookmarks);
      $("pdf-thumbnails").append(details);
    }
    this.thumbnailObserver = new IntersectionObserver(
      async (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          this.thumbnailObserver.unobserve(entry.target);
          try {
            const page = await doc.getPage(Number(entry.target.dataset.page));
            if (doc !== this.document) return;
            const viewport = page.getViewport({
              scale: 80 / page.getViewport({ scale: 1 }).width,
            });
            const canvas = entry.target.querySelector("canvas");
            canvas.width = Math.ceil(viewport.width);
            canvas.height = Math.ceil(viewport.height);
            await page.render({
              canvasContext: canvas.getContext("2d"),
              viewport,
            }).promise;
          } catch (error) {
            if (doc === this.document) this.onError(error);
          }
        }
      },
      { root: $("pdf-thumbnails"), rootMargin: "150px" },
    );
    for (let number = 1; number <= doc.numPages; number++) {
      const button = document.createElement("button");
      button.className = "thumbnail";
      button.dataset.page = number;
      button.title = `Page ${number}`;
      const canvas = document.createElement("canvas");
      canvas.width = 80;
      canvas.height = 112;
      const label = document.createElement("span");
      label.textContent = number;
      button.append(canvas, label);
      button.onclick = () => this.go(number);
      $("pdf-thumbnails").append(button);
      this.thumbnailObserver.observe(button);
    }
  }
  setSinglePage(enabled) {
    this.viewer.scrollMode = enabled
      ? components.ScrollMode.PAGE
      : components.ScrollMode.VERTICAL;
  }
  async setFormTest(enabled) {
    if (!this.artifact) return;
    if (this.formTest === enabled) return;
    this.formTest = enabled;
    // PDFViewer's annotation mode is immutable; use a new viewer for form mode.
    this.viewer.setDocument(null);
    this.viewerAbort.abort();
    this.viewerAbort = new AbortController();
    this.viewer = new components.PDFViewer({
      container: $("pdf-container"),
      viewer: $("pdf-viewer"),
      eventBus: this.eventBus,
      linkService: this.linkService,
      findController: this.findController,
      annotationMode: enabled
        ? pdfjs.AnnotationMode.ENABLE_FORMS
        : pdfjs.AnnotationMode.ENABLE,
      enableAutoLinking: false,
      imageResourcesPath: base + "web/images/",
      maxCanvasPixels: 8 * 1024 * 1024,
      abortSignal: this.viewerAbort.signal,
    });
    this.linkService.setViewer(this.viewer);
    this.viewer.setDocument(this.document);
  }
}
