"""Version-specific, conservative WeasyPrint checkpoint adapter for previews.

Never persist Python layout objects to disk. The cache belongs to one isolated
worker and one stable snapshot path. Export continues to use the public API.
"""

from __future__ import annotations

import copy
import hashlib
import logging
from pathlib import Path
from xml.etree import ElementTree

import weasyprint


class IncrementalPreview:
    # These internals have been verified against this exact release. Other
    # versions keep the public full-render path, rather than guessing an ABI.
    supported_version = "68.1"

    def __init__(self):
        self.cache = None
        self.font_config = None
        self.stats = {}

    def clear(self):
        self.cache = None
        self.font_config = None

    def write_pdf(self, markup, base_url, output, options, *, inputs="", visible_page=1, emit=None):
        from md_doc.builders.pdf import _make_url_fetcher

        html = weasyprint.HTML(string=markup, base_url=base_url, url_fetcher=_make_url_fetcher())
        if weasyprint.__version__ != self.supported_version or options.get("pdf_forms"):
            self.clear()
            html.write_pdf(str(output), **options)
            self.stats = {"mode": "full", "reason": "version or interactive forms"}
            return
        try:
            self._render(html, output, options, inputs, visible_page, emit)
        except Exception as exc:
            # A failed checkpoint must not leave an authoritative partial PDF.
            self.clear()
            if emit:
                emit({"type": "reset"})
            html.write_pdf(str(output), **options)
            logging.getLogger(__name__).debug("Checkpoint fallback", exc_info=True)
            self.stats = {"mode": "full", "reason": f"checkpoint fallback: {type(exc).__name__}"}

    @staticmethod
    def _styles(box, cache=None):
        from weasyprint.css.properties import INITIAL_VALUES

        key = id(box.style)
        if cache is not None and key in cache:
            return cache[key]
        values = tuple((name, repr(box.style[name])) for name in sorted(INITIAL_VALUES))
        result = hashlib.sha256(repr(values).encode()).digest()
        if cache is not None:
            cache[key] = result
        return result

    @classmethod
    def _signature(cls, box, style_cache=None):
        """Compare computed styles too: selectors can affect earlier siblings."""
        if style_cache is None:
            style_cache = {}
        attributes = (
            tuple(sorted((key, value) for key, value in box.element.attrib.items()))
            if box.element is not None
            else ()
        )
        replacement_content = (
            ElementTree.tostring(box.element)
            if box.element is not None and hasattr(box, "replacement")
            else None
        )
        return (
            type(box).__name__,
            box.element_tag,
            (getattr(box, "text", None), attributes, replacement_content),
            cls._styles(box, style_cache),
            tuple(cls._signature(child, style_cache) for child in box.all_children()),
        )

    @classmethod
    def _changed_path(cls, before, after, path=()):
        if before[:4] != after[:4]:
            return path
        for index, (left, right) in enumerate(zip(before[4], after[4])):
            if left != right:
                return cls._changed_path(left, right, path + (index,))
        if len(before[4]) != len(after[4]):
            index = min(len(before[4]), len(after[4]))
            return path + (min(index, len(before[4]) - 1),) if before[4] else path
        return None

    @staticmethod
    def _body(root):
        return next((box for box in root.children if box.element_tag == "body"), None)

    @staticmethod
    def _block_indices(page, element_indices):
        return {
            element_indices[box.element]
            for box in page.descendants()
            if box.element in element_indices
        }

    def _render(self, html, output, options, inputs, visible_page, emit):
        from weasyprint.css.counters import CounterStyle
        from weasyprint.document import Document
        from weasyprint.formatting_structure.build import build_formatting_structure
        from weasyprint.layout import initialize_page_maker
        from weasyprint.layout.page import make_all_pages
        from weasyprint.text.fonts import FontConfiguration

        head = html.etree_element.find("head")
        global_styles = b"".join(
            ElementTree.tostring(element)
            for element in html.etree_element.iter()
            if element.tag == "style"
            or (element.tag == "link" and "stylesheet" in element.get("rel", "").split())
        )
        global_key = hashlib.sha256(
            (inputs + str(base_url := html.base_url)).encode()
            + ElementTree.tostring(head)
            + global_styles
        ).hexdigest()
        if self.cache and self.cache["global"] != global_key:
            self.clear()
        if self.font_config is None:
            self.font_config = FontConfiguration()
        counter_style = CounterStyle()
        wp_options = weasyprint.DEFAULT_OPTIONS.copy()
        wp_options.update({key: value for key, value in options.items() if key != "finisher"})
        context = Document._build_layout_context(
            html, self.font_config, counter_style, {}, wp_options
        )
        body_element = html.etree_element.find("body")
        # Reports have a single outer div. Identify nested elements separately
        # so a changed paragraph does not invalidate that entire wrapper.
        element_indices = {element: index for index, element in enumerate(body_element.iter())}
        root = build_formatting_structure(
            html.etree_element,
            context.style_for,
            context.get_image_from_uri,
            base_url,
            context.target_collector,
            counter_style,
            context.footnotes,
        )
        elements = {}

        def index_elements(element, path=()):
            elements[path] = element
            for index, child in enumerate(element):
                index_elements(child, path + (index,))

        index_elements(html.etree_element)
        body = self._body(root)
        if body is None:
            raise ValueError("No normal body formatting tree")
        signatures = self._signature(body)
        nodes = {}

        def index_boxes(box, path=()):
            element = box.element
            nodes[path] = {
                "block": element_indices.get(element),
                "atomic": box.element_tag
                in {"table", "p", "pre", "h1", "h2", "h3", "h4", "h5", "h6"}
                or (element is not None and "keep-with-next" in element.get("class", "").split()),
            }
            for index, child in enumerate(box.all_children()):
                index_boxes(child, path + (index,))

        index_boxes(body)
        geometry = (self._styles(root), self._styles(body))
        unsafe = self._unsafe(root, context)
        if unsafe:
            self.clear()
            html.write_pdf(str(output), **options)
            self.stats = {"mode": "full", "reason": unsafe, "reused_pages": 0}
            return
        old = self.cache
        restart = 0
        changed = 0
        reason = "first render"
        if old and not unsafe and old["geometry"] == geometry:
            changed_path = self._changed_path(old["signatures"], signatures)
            if changed_path is None:
                changed = len(old["pages"])
                restart = changed
                reason = "unchanged composed content"
            else:
                # Column widths and keep-with-next grouping can change from
                # the beginning of their enclosing block.
                atomic = [
                    changed_path[:i]
                    for i in range(len(changed_path) + 1)
                    if old["nodes"].get(changed_path[:i], {}).get("atomic")
                ]
                if atomic:
                    changed_path = atomic[0]
                block = old["nodes"].get(changed_path, {}).get("block")
                affected = [i for i, indices in enumerate(old["mapping"]) if block in indices]
                changed = affected[0] if affected else 0
                restart = max(0, changed - 10)
                reason = "inline content edit"
        elif old:
            reason = unsafe or "page geometry changed"

        initialize_page_maker(context, root)
        while restart and not old["boundaries"][restart]:
            restart -= 1
        pages = []
        if restart:
            context.page_maker = copy.deepcopy(old["checkpoints"][: restart + 1])
            pages = [page.deepcopy() for page in old["pages"][:restart]]
            for page in pages:
                for box in page.descendants():
                    path = old["elements"].get(box.element)
                    if path is not None and path in elements:
                        box.element = elements[path]
            for checkpoint in context.page_maker:
                checkpoint[-1].update(content_changed=False, pages_wanted=False)
            context.page_maker[-1][-1]["content_changed"] = restart < len(old["pages"])
            self._restore_running(context, old["running"], restart)
            from weasyprint.layout.page import set_page_type_computed_styles

            for page in pages:
                set_page_type_computed_styles(page.page_type, html, context.style_for)

        original_footnotes = context.footnotes.copy()
        initial_count = len(old["pages"]) if old else 0
        laid_out = 0
        progressive_sent = False
        boundaries = [True]
        for loop in range(8):
            if loop:
                context.footnotes = original_footnotes.copy()
            previous_count = initial_count
            made = []
            for index, page in enumerate(make_all_pages(context, root, html, pages)):
                made.append(page)
                if loop == 0:
                    boundaries.append(
                        old["boundaries"][index + 1]
                        if old and index < restart
                        else not context.broken_out_of_flow and not context.reported_footnotes
                    )
                if loop == 0 and index >= restart:
                    laid_out += 1
                # Publish the visible page immediately, before pagination of
                # the tail. Global counters use the previous total for now.
                if (
                    not unsafe
                    and emit
                    and not progressive_sent
                    and index + 1 == visible_page
                    and index >= restart
                ):
                    for previous_index, previous_page in enumerate(made[:-1]):
                        self._collect_strings(context, previous_page, previous_index)
                    provisional = self._finish_page(
                        context, page.deepcopy(), made, index, initial_count or index + 1
                    )
                    document = self._document(html, [provisional])
                    partial = Path(output).with_name(f".md-doc-preview-page-{visible_page}.pdf")
                    document.write_pdf(str(partial))
                    emit({"type": "page", "page": visible_page, "path": str(partial)})
                    progressive_sent = True
            pages = made
            initial_count = len(pages)
            repeat = False
            for checkpoint in context.page_maker:
                checkpoint[3][1]["pages"] = [initial_count]
                state = checkpoint[-1]
                repeat |= state["content_changed"] or (
                    state["pages_wanted"] and previous_count != initial_count
                )
            if not repeat:
                break
        else:
            raise ValueError("Pagination did not converge")

        raw_pages = [page.deepcopy() for page in pages]
        checkpoints = copy.deepcopy(context.page_maker)
        running = self._copy_running(context.running_elements)
        # Rebuild only margin/fixed furniture on the prefix, including its
        # Page N of M labels. Body layout on these pages remains cached.
        context.string_set.clear()
        seen = set()
        finished = []
        for index, page in enumerate(pages):
            for box in page.descendants():
                if box.bookmark_label:
                    key = (box.element, box.element_tag)
                    if key in seen:
                        box.bookmark_label = ""
                    seen.add(key)
            finished.append(self._finish_page(context, page, pages, index, len(pages)))
        rendering = self._document(html, finished)
        rendering.write_pdf(str(output), **options)
        mapping = [sorted(self._block_indices(page, element_indices)) for page in raw_pages]
        self.cache = (
            None
            if unsafe
            else {
                "global": global_key,
                "geometry": geometry,
                "signatures": signatures,
                "nodes": nodes,
                "boundaries": boundaries,
                "pages": raw_pages,
                "checkpoints": checkpoints,
                "running": running,
                "mapping": mapping,
                "elements": {element: path for path, element in elements.items()},
            }
        )
        self.stats = {
            "mode": "incremental" if restart else "full",
            "reason": unsafe or reason,
            "reused_pages": restart,
            "restart_page": restart + 1,
            "changed_page": changed + 1,
            "pages": len(pages),
            "laid_out_pages": laid_out,
            "page_blocks": mapping,
        }

    @staticmethod
    def _unsafe(root, context):
        if context.footnotes or context.target_collector.counter_lookup_items:
            return "footnotes or cross-reference counters"
        cover_elements = set()
        for box in root.descendants():
            if box.element is not None and "cover" in box.element.get("class", "").split():
                cover_elements.update(box.element.iter())
        for box in root.descendants():
            style = box.style
            hidden_date = (
                box.element is not None
                and box.element.get("class") == "running-date"
                and style["visibility"] == "hidden"
            )
            if style["float"] != "none" or (
                style["position"] == "absolute"
                and not hidden_date
                and box.element not in cover_elements
            ):
                return "floating or absolutely positioned content"
            if style["column_count"] != "auto" or style["column_width"] != "auto":
                return "multi-column layout"
            if any(value in style["display"] for value in ("flex", "grid")):
                return "flex or grid layout"
            if "pages" in repr(style["content"]) and box.element_tag not in (None, "@page"):
                return "total-page counter in body"
        return None

    @staticmethod
    def _copy_running(running):
        return {
            name: {page: list(values) for page, values in by_page.items()}
            for name, by_page in running.items()
        }

    @staticmethod
    def _restore_running(context, running, restart):
        for name, by_page in running.items():
            for page, values in by_page.items():
                if page <= restart:
                    context.running_elements[name][page] = list(values)

    def _document(self, html, page_boxes):
        from weasyprint.document import Document, DocumentMetadata, Page
        from weasyprint.html import get_html_metadata

        document = Document(
            [Page(page) for page in page_boxes],
            DocumentMetadata(**get_html_metadata(html)),
            html.url_fetcher,
            self.font_config,
            {},
        )
        document._html = html
        return document

    @staticmethod
    def _collect_strings(context, page, index):
        assignments = {}
        for child in page.descendants():
            if child.string_set and child.string_set != "none":
                for name, text in child.string_set:
                    assignments.setdefault(name, []).append(text)
        for name, values in assignments.items():
            context.string_set[name][index + 1] = values

    @classmethod
    def _finish_page(cls, context, page, pages, index, total):
        from weasyprint.layout import layout_fixed_boxes
        from weasyprint.layout.background import layout_backgrounds
        from weasyprint.layout.page import make_margin_boxes

        cls._collect_strings(context, page, index)
        root, footnotes = page.children
        root.children = (
            list(layout_fixed_boxes(context, pages[:index], page))
            + list(root.children)
            + list(layout_fixed_boxes(context, pages[index + 1 :], page))
        )
        context.current_page = index + 1
        context.page_bottom = page.content_box_y() + page.height
        state = copy.deepcopy(context.page_maker[index + 1][3])
        state[1]["pages"] = [total]
        page.children = (root,)
        if footnotes.children:
            page.children += (footnotes,)
        page.children += tuple(make_margin_boxes(context, page, state))
        layout_backgrounds(page, context.get_image_from_uri)
        return page
