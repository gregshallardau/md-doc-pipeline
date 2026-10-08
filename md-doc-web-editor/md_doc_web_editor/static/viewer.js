/* Locally bundled PDF.js. Document JavaScript and external links are disabled. */
import * as pdfjs from "./vendor/pdfjs-6.4.299/legacy/build/pdf.min.mjs";
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
    });
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
  invalidate() {
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
