from __future__ import annotations

from pathlib import Path
import sys
import traceback

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QDragEnterEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pdfdiffstudio import __version__
from pdfdiffstudio.pdf_compare import PdfComparisonResult, VisualDiffResult, compare_pdfs, render_visual_diff


APP_NAME = "PDF Diff Studio"


class PdfSlot(QFrame):
    file_changed = Signal(str)

    def __init__(self, title: str) -> None:
        super().__init__()
        self._path: Path | None = None
        self.setAcceptDrops(True)
        self.setObjectName("pdfSlot")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("slotTitle")
        self.file_label = QLabel("No PDF selected")
        self.file_label.setObjectName("fileLabel")
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.file_label.setWordWrap(True)

        self.browse_button = QPushButton("Attach PDF")
        self.browse_button.clicked.connect(self._browse)
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear)

        buttons = QHBoxLayout()
        buttons.addWidget(self.browse_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        layout.addWidget(self.title_label)
        layout.addWidget(self.file_label)
        layout.addLayout(buttons)

    @property
    def path(self) -> Path | None:
        return self._path

    def set_path(self, path: str | Path) -> None:
        pdf_path = Path(path)
        self._path = pdf_path
        self.file_label.setText(str(pdf_path))
        self.file_changed.emit(str(pdf_path))

    def clear(self) -> None:
        self._path = None
        self.file_label.setText("No PDF selected")
        self.file_changed.emit("")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._first_pdf_url(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        url = self._first_pdf_url(event)
        if not url:
            event.ignore()
            return
        self.set_path(url.toLocalFile())
        event.acceptProposedAction()

    def _browse(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, "Attach PDF", "", "PDF files (*.pdf)")
        if selected:
            self.set_path(selected)

    @staticmethod
    def _first_pdf_url(event: QDragEnterEvent | QDropEvent):
        if not event.mimeData().hasUrls():
            return None
        for url in event.mimeData().urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf"):
                return url
        return None


class CompareWorker(QThread):
    progress = Signal(str, int)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, left_path: Path, right_path: Path) -> None:
        super().__init__()
        self.left_path = left_path
        self.right_path = right_path

    def run(self) -> None:
        try:
            result = compare_pdfs(self.left_path, self.right_path, self.progress.emit)
            self.completed.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc())


class VisualWorker(QThread):
    completed = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, left_path: Path, right_path: Path, page_index: int) -> None:
        super().__init__()
        self.left_path = left_path
        self.right_path = right_path
        self.page_index = page_index

    def run(self) -> None:
        try:
            result = render_visual_diff(self.left_path, self.right_path, self.page_index)
            self.completed.emit(self.page_index, result)
        except Exception:
            self.failed.emit(self.page_index, traceback.format_exc())


class ImagePane(QWidget):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = QLabel(title)
        self.title.setObjectName("imagePaneTitle")
        self.image_label = QLabel("No preview")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.image_label.setMinimumSize(240, 260)
        self._pixmap: QPixmap | None = None

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.image_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.title)
        layout.addWidget(self.scroll_area, 1)

    def set_image(self, path: Path) -> None:
        self._pixmap = QPixmap(str(path))
        self._refresh()

    def set_message(self, message: str) -> None:
        self._pixmap = None
        self.image_label.setText(message)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            return
        viewport = self.scroll_area.viewport().size()
        scaled = self._pixmap.scaled(
            max(120, viewport.width() - 12),
            max(120, viewport.height() - 12),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1320, 820)
        self.result: PdfComparisonResult | None = None
        self.compare_worker: CompareWorker | None = None
        self.visual_worker: VisualWorker | None = None
        self.visual_workers: list[VisualWorker] = []
        self._syncing_scroll = False

        self._build_ui()
        self._apply_style()
        self._update_compare_state()

    def _build_ui(self) -> None:
        self.left_slot = PdfSlot("First PDF")
        self.right_slot = PdfSlot("Second PDF")
        self.left_slot.file_changed.connect(self._update_compare_state)
        self.right_slot.file_changed.connect(self._update_compare_state)

        self.compare_button = QPushButton("Compare")
        self.compare_button.setObjectName("primaryButton")
        self.compare_button.clicked.connect(self._start_compare)

        self.open_left_action = QAction("Open first PDF", self)
        self.open_left_action.triggered.connect(lambda: self._open_pdf(self.left_slot.path))
        self.open_right_action = QAction("Open second PDF", self)
        self.open_right_action.triggered.connect(lambda: self._open_pdf(self.right_slot.path))

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.addAction(self.open_left_action)
        toolbar.addAction(self.open_right_action)
        self.addToolBar(toolbar)

        self.summary_label = QLabel("Attach two PDFs to compare.")
        self.summary_label.setObjectName("summaryLabel")
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setRange(0, 100)

        self.page_list = QListWidget()
        self.page_list.currentRowChanged.connect(self._show_page)

        self.left_text = QTextBrowser()
        self.right_text = QTextBrowser()
        for browser in (self.left_text, self.right_text):
            browser.setOpenExternalLinks(False)
            browser.setLineWrapMode(QTextBrowser.LineWrapMode.NoWrap)
        self.left_text.verticalScrollBar().valueChanged.connect(lambda value: self._sync_scroll(self.left_text, self.right_text, value))
        self.right_text.verticalScrollBar().valueChanged.connect(lambda value: self._sync_scroll(self.right_text, self.left_text, value))

        text_splitter = QSplitter(Qt.Orientation.Horizontal)
        text_splitter.addWidget(self._labeled_widget("First PDF", self.left_text))
        text_splitter.addWidget(self._labeled_widget("Second PDF", self.right_text))
        text_splitter.setSizes([1, 1])

        self.left_image = ImagePane("First PDF")
        self.right_image = ImagePane("Second PDF")
        self.overlay_image = ImagePane("Changes")
        visual_splitter = QSplitter(Qt.Orientation.Horizontal)
        visual_splitter.addWidget(self.left_image)
        visual_splitter.addWidget(self.right_image)
        visual_splitter.addWidget(self.overlay_image)
        visual_splitter.setSizes([1, 1, 1])

        self.visual_note = QLabel("Select a page to render its visual comparison.")
        self.visual_note.setObjectName("visualNote")
        visual_container = QWidget()
        visual_layout = QVBoxLayout(visual_container)
        visual_layout.setContentsMargins(0, 0, 0, 0)
        visual_layout.setSpacing(8)
        visual_layout.addWidget(self.visual_note)
        visual_layout.addWidget(visual_splitter, 1)

        self.tabs = QTabWidget()
        self.tabs.addTab(text_splitter, "Text")
        self.tabs.addTab(visual_container, "Visual")

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        left_layout.addWidget(self.summary_label)
        left_layout.addWidget(self.page_list, 1)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(self.tabs)
        main_splitter.setSizes([330, 990])

        attach_layout = QGridLayout()
        attach_layout.setColumnStretch(0, 1)
        attach_layout.setColumnStretch(1, 1)
        attach_layout.addWidget(self.left_slot, 0, 0)
        attach_layout.addWidget(self.right_slot, 0, 1)
        attach_layout.addWidget(self.compare_button, 0, 2)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(16, 12, 16, 16)
        root_layout.setSpacing(12)
        root_layout.addLayout(attach_layout)
        root_layout.addWidget(self.progress)
        root_layout.addWidget(main_splitter, 1)

        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background: #f6f3ea;
            }
            QFrame#pdfSlot {
                background: #fffdf7;
                border: 1px solid #d7d1c2;
                border-radius: 8px;
            }
            QLabel#slotTitle, QLabel#summaryLabel, QLabel#imagePaneTitle {
                font-weight: 700;
                color: #232323;
            }
            QLabel#fileLabel {
                color: #4b5563;
            }
            QLabel#visualNote {
                color: #4b5563;
                padding: 2px 0;
            }
            QPushButton {
                padding: 7px 12px;
                border: 1px solid #b9b09b;
                border-radius: 6px;
                background: #fffaf0;
                color: #242424;
            }
            QPushButton:hover {
                background: #f5eddc;
            }
            QPushButton:disabled {
                color: #999;
                background: #eeeae0;
            }
            QPushButton#primaryButton {
                min-width: 116px;
                font-weight: 700;
                background: #273b2d;
                border-color: #273b2d;
                color: white;
            }
            QPushButton#primaryButton:hover {
                background: #34503d;
            }
            QListWidget, QTextBrowser, QScrollArea {
                background: #fffdf8;
                border: 1px solid #d7d1c2;
                border-radius: 6px;
            }
            QTabWidget::pane {
                border: 1px solid #d7d1c2;
                border-radius: 6px;
                background: #fffdf8;
            }
            QTabBar::tab {
                padding: 8px 14px;
            }
            """
        )

    def _update_compare_state(self) -> None:
        ready = self.left_slot.path is not None and self.right_slot.path is not None
        busy = self.compare_worker is not None and self.compare_worker.isRunning()
        self.compare_button.setEnabled(ready and not busy)
        self.open_left_action.setEnabled(self.left_slot.path is not None)
        self.open_right_action.setEnabled(self.right_slot.path is not None)

    def _start_compare(self) -> None:
        if self.left_slot.path is None or self.right_slot.path is None:
            return
        self.result = None
        self.page_list.clear()
        self.left_text.clear()
        self.right_text.clear()
        self._set_visual_messages("Waiting for comparison")
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.summary_label.setText("Comparing PDFs...")
        self.statusBar().showMessage("Comparing PDFs")

        self.compare_worker = CompareWorker(self.left_slot.path, self.right_slot.path)
        self.compare_worker.progress.connect(self._on_progress)
        self.compare_worker.completed.connect(self._on_compare_done)
        self.compare_worker.failed.connect(self._on_compare_failed)
        self.compare_worker.finished.connect(self._on_compare_finished)
        self.compare_worker.start()
        self._update_compare_state()

    def _on_progress(self, message: str, percent: int) -> None:
        self.progress.setValue(percent)
        self.statusBar().showMessage(message)

    def _on_compare_done(self, result: PdfComparisonResult) -> None:
        self.result = result
        self._populate_pages(result)
        self.summary_label.setText(
            f"{result.changed_pages} of {len(result.pages)} pages changed  |  "
            f"+{result.added_lines}  -{result.removed_lines}  ~{result.changed_lines}"
        )
        first_changed = next((index for index, page in enumerate(result.pages) if page.is_changed), 0)
        if result.pages:
            self.page_list.setCurrentRow(first_changed)
        self.statusBar().showMessage("Comparison complete")

    def _on_compare_failed(self, detail: str) -> None:
        self.summary_label.setText("Comparison failed.")
        self.statusBar().showMessage("Comparison failed")
        QMessageBox.critical(self, "Comparison failed", detail)

    def _on_compare_finished(self) -> None:
        self.progress.setVisible(False)
        self.compare_worker = None
        self._update_compare_state()

    def _populate_pages(self, result: PdfComparisonResult) -> None:
        self.page_list.clear()
        for page in result.pages:
            similarity = int(page.similarity * 100)
            item = QListWidgetItem(
                f"Page {page.page_number:>3}   {page.status:<9}   "
                f"+{page.added_lines} -{page.removed_lines} ~{page.changed_lines}   {similarity}%"
            )
            if page.status == "Unchanged":
                item.setForeground(QColor("#4b5563"))
            elif page.status == "Added":
                item.setBackground(QColor("#e7f6ea"))
            elif page.status == "Removed":
                item.setBackground(QColor("#ffe7e4"))
            else:
                item.setBackground(QColor("#fff5cf"))
            self.page_list.addItem(item)

    def _show_page(self, row: int) -> None:
        if self.result is None or row < 0 or row >= len(self.result.pages):
            return
        page = self.result.pages[row]
        self.left_text.setHtml(page.left_html)
        self.right_text.setHtml(page.right_html)
        self._render_visual_page(row)

    def _render_visual_page(self, page_index: int) -> None:
        if self.result is None:
            return
        self._set_visual_messages("Rendering page preview...")
        self.visual_note.setText(f"Rendering visual comparison for page {page_index + 1}.")
        self.visual_worker = VisualWorker(self.result.left_path, self.result.right_path, page_index)
        self.visual_workers.append(self.visual_worker)
        self.visual_worker.completed.connect(self._on_visual_done)
        self.visual_worker.failed.connect(self._on_visual_failed)
        self.visual_worker.finished.connect(self._on_visual_finished)
        self.visual_worker.start()

    def _on_visual_done(self, page_index: int, result: VisualDiffResult) -> None:
        if self.page_list.currentRow() != page_index:
            return
        self.left_image.set_image(result.left_image)
        self.right_image.set_image(result.right_image)
        self.overlay_image.set_image(result.overlay_image)
        self.visual_note.setText(f"Page {page_index + 1}: visual change area {result.changed_ratio:.2%}.")

    def _on_visual_failed(self, page_index: int, detail: str) -> None:
        if self.page_list.currentRow() != page_index:
            return
        self._set_visual_messages("Visual preview failed")
        self.visual_note.setText(f"Page {page_index + 1}: visual preview failed.")
        self.statusBar().showMessage("Visual preview failed")
        QMessageBox.warning(self, "Visual preview failed", detail)

    def _on_visual_finished(self) -> None:
        worker = self.sender()
        if worker in self.visual_workers:
            self.visual_workers.remove(worker)
        if worker is self.visual_worker:
            self.visual_worker = None

    def _set_visual_messages(self, message: str) -> None:
        self.left_image.set_message(message)
        self.right_image.set_message(message)
        self.overlay_image.set_message(message)

    def _sync_scroll(self, source: QTextBrowser, target: QTextBrowser, value: int) -> None:
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        target.verticalScrollBar().setValue(value)
        self._syncing_scroll = False

    def _open_pdf(self, path: Path | None) -> None:
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    @staticmethod
    def _labeled_widget(title: str, widget: QWidget) -> QWidget:
        label = QLabel(title)
        label.setObjectName("imagePaneTitle")
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(label)
        layout.addWidget(widget, 1)
        return container


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("PDF Diff Studio")
    window = MainWindow()
    window.show()
    return app.exec()
