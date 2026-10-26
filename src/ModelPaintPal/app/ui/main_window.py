# -*- coding: utf-8 -*-
"""主窗口：把取色、建议、可视化、历史收藏、设置串成一个工作流。

计算路径只有**一条**：``_request_compute()`` 负责"何时算"，``_compute()`` 负责
"怎么算"，``_render_suggestions()`` 负责"怎么画"。同步/异步、立即/防抖只是
入口参数不同，渲染逻辑不再有两份。
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QPushButton, QScrollArea,
    QSplitter, QStatusBar, QTabWidget, QVBoxLayout, QWidget,
)

from ..core.color_models import ColorSample
from ..core.config import AppConfig, load_config, save_config
from ..core.delta_e import grade_delta_e
from ..core.favorites_store import FavoritesStore
from ..core.history_store import HistoryStore
from ..core.hotkeys import HotkeyManager
from ..core.logging_setup import get_logger
from ..core.sample_record import SampleRecord
from ..data.paint_db import calibrate, get_database
from ..services.export_service import (
    copy_to_clipboard, recipe_to_text, suggestion_to_markdown, suggestions_to_json,
)
from ..services.async_suggest import submit_mix, submit_suggest
from ..services.async_verify import submit_verify
from ..services.paint_matcher import PaintMatcher, summarize
from ..services.scheme_engine import MixRecipe
from ..services.verify_service import VerifyReport, adopt
from .panels.coverage_panel import CoveragePanel
from .panels.verify_dialog import VerifyDialog
from .panels.library_panel import LibraryPanel
from .panels.pick_panel import PickPanel
from .panels.scheme_panel import SCHEME_TAB_TITLE, SchemePanel
from .panels.settings_panel import SettingsPanel
from .panels.suggest_panel import SuggestPanel
from .panels.visualize_panel import VisualizePanel
from .picker.picker_controller import PickerController
from .theme import Palette, stylesheet
from .onboarding import DEFAULT_STEPS, OnboardingOverlay, OnboardingStep
from .widgets.toast import show_toast

logger = get_logger(__name__)

__all__ = ["MainWindow"]

_HOTKEY_PICK = "pick"
_HOTKEY_COPY = "copy_hex"

# 颜色来源。调色微调产生的颜色不算"取色"：不写历史、不自动复制、不重置滑块。
_SOURCE_SCREEN = "screen"
_SOURCE_MANUAL = "manual"
_SOURCE_TUNE = "tune"
_SOURCE_TUNE_RESET = "tune_reset"

# 参数面板防抖：拖动 SpinBox 一次会触发几十次 valueChanged，
# 每次都同步重算（约 140 ms）会让界面直接卡住。
_COMPUTE_DEBOUNCE_MS = 180


class MainWindow(QMainWindow):
    """应用主窗口。"""

    def __init__(self, config: Optional[AppConfig] = None) -> None:
        super().__init__()
        self._config: AppConfig = config or load_config()
        self._db = get_database()
        self._matcher = PaintMatcher(self._db)
        self._history = HistoryStore(limit=self._config.history_limit)
        self._favorites = FavoritesStore(limit=self._config.favorites_limit)

        self._sample: Optional[ColorSample] = None
        self._base_rgb: Optional[tuple] = None    # 微调基准（原始取色）
        self._suggestions: list = []
        self._brand_filter: List[str] = []        # [] = 不限品牌
        self._suggest_token: int = 0              # 异步计算的去抖令牌

        # 基础配色（五瓶基础漆调配）状态
        self._mix_recipe: Optional[MixRecipe] = None
        self._scheme_token: int = 0
        self._total_drops: int = int(getattr(self._config, "drop_total", 20) or 20)

        self._picker = PickerController(self)
        self._hotkeys = HotkeyManager(self)

        self._compute_timer = QTimer(self)
        self._compute_timer.setSingleShot(True)
        self._compute_timer.setInterval(_COMPUTE_DEBOUNCE_MS)
        self._compute_timer.timeout.connect(self._compute_async)

        from .. import __version__

        self.setWindowTitle(f"3D 打印模型涂装配色助手  ModelPaintPal v{__version__}")
        self.resize(self._config.window_width, self._config.window_height)
        self.setMinimumSize(960, 600)
        self.setStyleSheet(stylesheet())

        self._build_ui()
        self._build_menu()
        self._connect_signals()
        self._refresh_library()
        self._apply_hotkeys()
        self._update_status("就绪")

        if self._config.show_onboarding:
            QTimer.singleShot(420, self._start_onboarding)

    # ================================================================== 构建
    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(10)

        root.addWidget(self._build_header())

        splitter = QSplitter(Qt.Horizontal, central)
        splitter.setChildrenCollapsible(False)
        self._splitter = splitter
        root.addWidget(splitter, 1)
        splitter.addWidget(self._build_left_column(splitter))
        splitter.addWidget(self._build_right_column(splitter))
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([360, 760])

        self.setStatusBar(QStatusBar(self))
        self._suggest_panel.sync_settings(self._config.preferred_brands,
                                          self._config.delta_e_formula)
        # 设置页必须一建好就与真实配置对齐，否则控件停在各 SpinBox 的最小值，
        # 用户动一下任意开关就会把整套参数写成最小值。
        self._settings_panel.sync_from_config()

        self._onboarding = OnboardingOverlay(central, self._build_onboarding_steps())
        self._suggest_panel.show_empty()
        self._scheme_panel.show_empty()

    def _build_left_column(self, parent: QWidget) -> QScrollArea:
        """左列（放在滚动区里：窗口偏矮时不会把数值行压成裁切）。"""
        left_scroll = QScrollArea(parent)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setMinimumWidth(320)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.setSpacing(10)
        self._pick_panel = PickPanel(left)
        left_layout.addWidget(self._pick_panel)
        self._library = LibraryPanel(left)
        self._library.setMinimumHeight(220)
        left_layout.addWidget(self._library, 1)
        left_scroll.setWidget(left)
        return left_scroll

    def _build_right_column(self, parent: QWidget) -> QWidget:
        right = QWidget(parent)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        self._tabs = QTabWidget(right)
        self._suggest_panel = SuggestPanel(self._tabs)
        self._visualize_panel = VisualizePanel(self._tabs)
        self._scheme_panel = SchemePanel(self._tabs)
        self._scheme_panel.set_total_drops(self._total_drops)
        self._coverage_panel = CoveragePanel(self._config, self._tabs)
        self._settings_panel = SettingsPanel(self._config, self._tabs)
        self._tabs.addTab(self._suggest_panel, "配色建议")
        self._tabs.addTab(self._visualize_panel, "色卡对比")
        self._tabs.addTab(self._scheme_panel, SCHEME_TAB_TITLE)
        self._tabs.addTab(self._coverage_panel, "用量参数")
        self._tabs.addTab(self._settings_panel, "设置")
        right_layout.addWidget(self._tabs, 1)
        right.setMinimumWidth(480)
        return right

    def _build_menu(self) -> None:
        menu = self.menuBar()
        menu.setStyleSheet("QMenuBar { background-color: %s; }" % Palette.bg_alt)

        file_menu = menu.addMenu("文件")
        export_json = file_menu.addAction("导出建议为 JSON…")
        export_json.triggered.connect(self._export_json)
        export_md = file_menu.addAction("导出建议为 Markdown…")
        export_md.triggered.connect(self._export_markdown)
        export_csv = file_menu.addAction("导出建议为 CSV…")
        export_csv.triggered.connect(self._export_csv)
        file_menu.addSeparator()
        share_action = file_menu.addAction("复制分享文本")
        # 注意：Ctrl+Shift+C 是全局「复制色值」热键，这里必须避开，否则两个动作抢同一个组合键
        share_action.setShortcut("Ctrl+Alt+C")
        share_action.triggered.connect(self._copy_share_text)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("退出")
        quit_action.triggered.connect(self.close)

        view_menu = menu.addMenu("视图")
        for index in range(self._tabs.count()):
            title = self._tabs.tabText(index)
            action = view_menu.addAction(title)
            # Ctrl+1..4 直接切页：吸色时手不用离开键盘
            action.setShortcut(f"Ctrl+{index + 1}")
            action.triggered.connect(lambda _=False, i=index: self._tabs.setCurrentIndex(i))

        help_menu = menu.addMenu("帮助")
        guide = help_menu.addAction("新手引导")
        guide.triggered.connect(self._start_onboarding)
        shortcut = help_menu.addAction("创建桌面快捷方式")
        shortcut.triggered.connect(self._create_desktop_shortcut)
        about = help_menu.addAction("关于")
        about.triggered.connect(self._show_about)

    def _create_desktop_shortcut(self) -> None:
        from ..core.shortcut import ensure_desktop_shortcut

        result = ensure_desktop_shortcut()
        show_toast(self, "桌面快捷方式已就绪" if result else
                   "创建未成功，请查看日志；也可为 ModelPaintPal.exe 手动创建快捷方式")

    def _build_header(self) -> QFrame:
        header = QFrame(self)
        header.setObjectName("Card")
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(12)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("3D 打印模型涂装配色助手")
        title.setObjectName("TitleLabel")
        title.setObjectName("SectionLabel")
        subtitle = QLabel("吸色 → 找漆 → 给配比 → 估用量 · 数据仅供配漆参考，正式喷涂请先试喷")
        subtitle.setObjectName("SubTitleLabel")
        subtitle.setObjectName("DimLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        row.addLayout(title_box, 1)

        self._db_label = QLabel("")
        self._db_label.setObjectName("FaintLabel")
        row.addWidget(self._db_label, 0, Qt.AlignRight | Qt.AlignVCenter)

        self._guide_button = QPushButton("新手引导")
        self._guide_button.setObjectName("GhostButton")
        self._guide_button.clicked.connect(self._start_onboarding)
        row.addWidget(self._guide_button)

        self._settings_button = QPushButton("设置")
        self._settings_button.setObjectName("GhostButton")
        self._settings_button.clicked.connect(lambda: self._tabs.setCurrentWidget(self._settings_panel))
        row.addWidget(self._settings_button)

        self._refresh_db_label()
        return header

    def _build_onboarding_steps(self) -> List[OnboardingStep]:
        steps = list(DEFAULT_STEPS)
        if steps:
            steps[0].target_getter = lambda: self._pick_panel
        if len(steps) > 1:
            steps[1].target_getter = lambda: self._tabs
        if len(steps) > 3:
            steps[3].target_getter = lambda: self._library
        return steps

    # ================================================================== 信号
    def _connect_signals(self) -> None:
        # 取色
        self._pick_panel.pickRequested.connect(self._start_picking)
        self._pick_panel.copyRequested.connect(self._on_copy_value)
        self._pick_panel.favoriteRequested.connect(self._favorite_current)
        self._pick_panel.manualSubmitted.connect(self._on_manual_color)
        self._pick_panel.tuneChanged.connect(self._on_tune_changed)
        self._pick_panel.tuneReset.connect(self._on_tune_reset)

        self._picker.colorPicked.connect(self._on_color_picked)
        self._picker.cancelled.connect(self._on_pick_cancelled)
        self._picker.failed.connect(self._on_pick_failed)

        # 建议区
        self._suggest_panel.pickRequested.connect(self._start_picking)
        self._suggest_panel.copyRecipeRequested.connect(self._on_copy_recipe)
        self._suggest_panel.copyMarkdownRequested.connect(self._on_copy_markdown)
        self._suggest_panel.calibrateRequested.connect(self._on_calibrate_requested)
        self._suggest_panel.verifyRequested.connect(self._on_verify_requested)
        self._suggest_panel.brandFilterChanged.connect(self._on_brand_filter_changed)
        self._suggest_panel.formulaChanged.connect(self._on_formula_changed)

        # 可视化
        self._visualize_panel.swatchClicked.connect(self._on_swatch_clicked)
        self._visualize_panel.pickRequested.connect(self._start_picking)

        # 基础配色
        self._scheme_panel.pickRequested.connect(self._start_picking)
        self._scheme_panel.copyRecipeRequested.connect(self._on_copy_recipe)
        self._scheme_panel.copyMarkdownRequested.connect(self._on_copy_markdown)
        self._scheme_panel.calibrateRequested.connect(self._on_calibrate_requested)
        self._scheme_panel.verifyRequested.connect(self._on_verify_requested)
        self._scheme_panel.mixRequested.connect(self._on_mix_requested)

        # 用量参数
        self._coverage_panel.configChanged.connect(self._on_coverage_changed)

        # 设置
        self._settings_panel.hotkeysChanged.connect(self._apply_hotkeys)
        self._settings_panel.onboardingRequested.connect(self._start_onboarding)
        self._settings_panel.databaseChanged.connect(self._on_database_changed)
        self._settings_panel.settingsChanged.connect(self._on_settings_changed)

        # 切页：进入「基础配色」时按需补算
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # 历史 / 收藏
        self._library.colorSelected.connect(self._on_library_color_selected)
        self._library.historyRemoved.connect(self._on_history_removed)
        self._library.favoriteRemoved.connect(self._on_favorite_removed)
        self._library.favoriteAdded.connect(self._on_favorite_added)
        self._library.historyCleared.connect(self._on_history_cleared)
        self._library.favoritesCleared.connect(self._on_favorites_cleared)
        self._library.pickRequested.connect(self._start_picking)

        # 热键
        self._hotkeys.triggered.connect(self._on_hotkey_triggered)
        self._hotkeys.failed.connect(self._on_hotkey_failed)

        # 引导
        self._onboarding.finished.connect(self._on_onboarding_done)
        self._onboarding.skipped.connect(self._on_onboarding_done)

    # ================================================================== 取色
    def _start_picking(self) -> None:
        self._configure_picker()
        if not self._picker.start():
            return
        self._pick_panel.set_picking(True)
        self._update_status("吸色中：移动鼠标选点，左键取样，右键/Esc 取消")

    def _configure_picker(self) -> None:
        self._picker.configure(
            grid=self._config.magnifier_grid,
            zoom=self._config.magnifier_zoom,
            follow=self._config.magnifier_follow,
            average=self._config.sample_average,
        )

    def _on_color_picked(self, rgb: Sequence[int]) -> None:
        self._pick_panel.set_picking(False)
        self._apply_color(tuple(rgb), source=_SOURCE_SCREEN, remember=True)

    def _on_manual_color(self, rgb: Sequence[int]) -> None:
        self._apply_color(tuple(rgb), source=_SOURCE_MANUAL, remember=True)

    def _on_pick_cancelled(self) -> None:
        self._pick_panel.set_picking(False)
        self._update_status("已取消吸色")

    def _on_pick_failed(self, message: str) -> None:
        self._pick_panel.set_picking(False)
        self._update_status(message)
        show_toast(self, message, "error")

    # ================================================================== 应用颜色
    def _apply_color(self, rgb, source: str = _SOURCE_SCREEN, remember: bool = True) -> None:
        """唯一的颜色入口：吸色 / 手动输入 / 历史载入 / 微调 都走这里。"""
        tuned = source in (_SOURCE_TUNE, _SOURCE_TUNE_RESET)
        sample = ColorSample.from_rgb(rgb, source=source)
        self._sample = sample
        self._pick_panel.set_sample(sample, sync_tuner=not tuned)
        if not tuned:
            self._base_rgb = sample.rgb
        if remember:
            self._history.add(SampleRecord(rgb=sample.rgb, source=source))
            self._refresh_library()
        if self._config.auto_copy_on_pick and not tuned:
            copy_to_clipboard(sample.hex)
        self._request_compute(immediate=True)
        self._request_mix_compute()
        if tuned and self._base_rgb is not None:
            self._update_status(
                f"微调中 {sample.hex}（原始 #{self._base_rgb[0]:02X}{self._base_rgb[1]:02X}"
                f"{self._base_rgb[2]:02X}），正在计算建议…")
        else:
            self._update_status(f"已取色 {sample.hex}，正在计算建议…")

    def _on_tune_changed(self, rgb: Sequence[int]) -> None:
        self._apply_color(tuple(rgb), source=_SOURCE_TUNE, remember=False)

    def _on_tune_reset(self) -> None:
        if self._base_rgb is not None:
            self._apply_color(self._base_rgb, source=_SOURCE_TUNE_RESET, remember=False)
            self._update_status(f"已还原为原始取色 {self._sample.hex}")

    # ================================================================== 计算
    def _request_compute(self, immediate: bool = False) -> None:
        """决定"什么时候算"：吸色要立刻反馈，拖参数要防抖。"""
        if self._sample is None:
            self._render_suggestions()
            return
        if immediate:
            self._compute_timer.stop()
            self._compute_async()
            return
        self._compute_timer.start()

    def _compute_async(self) -> None:
        """把计算丢到线程池；只采纳最新一次结果（token 去抖）。"""
        if self._sample is None:
            self._render_suggestions()
            return
        self._suggest_token += 1
        token = self._suggest_token
        self._suggest_panel.set_busy(True)
        submit_suggest(
            self._matcher, self._sample.rgb, self._config, self._brand_filter,
            self._coverage_panel.coverage_input(), token,
            self._on_suggest_ready, self._on_suggest_failed,
        )

    def _compute_now(self) -> None:
        """同步重算：用于校准/换库这类"必须立刻拿到新结果"的场景。"""
        if self._sample is None:
            self._suggestions = []
            self._render_suggestions()
            return
        try:
            self._suggestions = self._matcher.suggest(
                target_rgb=self._sample.rgb,
                config=self._config,
                brands=self._brand_filter,
                coverage_input=self._coverage_panel.coverage_input(),
            )
        except Exception as exc:  # 兜底：计算失败不阻塞 UI
            logger.exception("计算配色建议失败: %s", exc)
            self._suggestions = []
            show_toast(self, f"计算失败：{exc}", "error")
        self._render_suggestions()

    def _on_suggest_ready(self, suggestions: list, token: int) -> None:
        # 只采纳最新一次请求的结果，避免连续吸色时旧结果覆盖新结果（去抖）。
        if token != self._suggest_token:
            return
        self._suggestions = suggestions
        self._render_suggestions()
        self._update_status(f"已取色 {self._sample.hex} · {summarize(self._suggestions)}")

    def _on_suggest_failed(self, message: str, token: int) -> None:
        """计算失败：明确告知可以重试，而不是显示"没有找到可用建议"。"""
        if token != self._suggest_token:
            return
        self._suggestions = []
        self._suggest_panel.set_busy(False)
        self._suggest_panel.show_empty(
            "计算失败", f"{message}。可以重试，或在上方换个品牌范围。")
        self._visualize_panel.clear()
        self._coverage_panel.set_suggestions([])
        self._update_status(f"配色计算失败：{message}")
        show_toast(self, f"配色计算失败：{message}", "error", 4200)

    # ================================================================== 基础配色
    def _on_tab_changed(self, index: int) -> None:
        """切到「基础配色」页且已有吸色时，按需补算。"""
        if self._tabs.widget(index) is self._scheme_panel:
            self._request_mix_compute()

    def _on_mix_requested(self, total_drops: int) -> None:
        """面板改了总滴数或点了重算：记下来并重算（仅在该页可见时才会真正计算）。"""
        self._total_drops = int(total_drops)
        self._request_mix_compute()

    def _request_mix_compute(self) -> None:
        """基础配色（五瓶基础漆调配）只在「基础配色」页可见时计算，避免后台空转。"""
        if self._sample is None:
            self._scheme_panel.show_empty()
            return
        if self._tabs.currentWidget() is not self._scheme_panel:
            return
        self._scheme_token += 1
        token = self._scheme_token
        self._scheme_panel.set_busy(True)
        submit_mix(
            self._matcher, self._sample.rgb, self._config, self._brand_filter,
            self._coverage_panel.coverage_input(), self._total_drops,
            token, self._on_mix_ready, self._on_mix_failed,
        )

    def _on_mix_ready(self, recipe: MixRecipe, token: int) -> None:
        if token != self._scheme_token:
            return
        self._mix_recipe = recipe
        self._scheme_panel.set_mix_recipe(recipe, self._sample.rgb)
        self._update_status(
            f"已取色 {self._sample.hex} · 基础配色：红/黄/蓝/白/黑五瓶调配"
            f"（近似 ΔE {recipe.delta_e:.1f}）"
        )

    def _on_mix_failed(self, message: str, token: int) -> None:
        if token != self._scheme_token:
            return
        self._mix_recipe = None
        self._scheme_panel.set_busy(False)
        self._scheme_panel.show_empty("基础配色计算失败", f"{message}。可以重试，或在上方换个品牌范围。")
        self._update_status(f"基础配色计算失败：{message}")
        show_toast(self, f"基础配色计算失败：{message}", "error", 4200)

    def _render_suggestions(self) -> None:
        """把已算好的建议渲染到各面板（无重计算，主线程安全）。"""
        if not self._suggestions:
            self._suggest_panel.show_empty()
            self._visualize_panel.clear()
            self._coverage_panel.set_suggestions([])
            self._pick_panel.set_delta_text("")
            return
        self._suggest_panel.set_suggestions(self._suggestions, self._sample.rgb)
        self._visualize_panel.set_data(self._sample.rgb, self._suggestions)
        self._coverage_panel.set_suggestions(self._suggestions)

        best = self._suggestions[0]
        self._pick_panel.set_delta_text(
            f"最接近：{best.anchor.full_label} {best.anchor.name} · "
            f"ΔE {best.delta_e:.2f}（{grade_delta_e(best.delta_e).label}）"
        )

    # ================================================================== 复制/导出
    def _on_copy_value(self, label: str, value: str) -> None:
        if copy_to_clipboard(value):
            show_toast(self, f"已复制 {label}：{value}", "success")
        else:
            show_toast(self, "复制失败，请手动选择文本", "error")

    def _on_copy_recipe(self, suggestion) -> None:
        text = recipe_to_text(suggestion.recipe)
        if copy_to_clipboard(text):
            show_toast(self, "配方已复制到剪贴板", "success")
        else:
            show_toast(self, "复制失败", "error")

    def _on_copy_markdown(self, suggestion) -> None:
        text = suggestion_to_markdown(suggestion)
        if copy_to_clipboard(text):
            show_toast(self, "Markdown 已复制到剪贴板", "success")
        else:
            show_toast(self, "复制失败，请稍后重试", "error")

    def _on_swatch_clicked(self, uid: str) -> None:
        """色卡点击：uid 形如 ``brand:code`` 或空（目标色）。"""
        if not uid:
            return
        entry = self._db.get(uid)
        if entry is None:
            return
        copy_to_clipboard(entry.hex)
        show_toast(self, f"已复制 {entry.full_label} 色值 {entry.hex}", "info")

    def _export_json(self) -> None:
        self._save_text(self.export_report(), "配色建议.json", "JSON 文件 (*.json)")

    def _export_markdown(self) -> None:
        if self._sample is None:
            show_toast(self, "还没有取色", "warn")
            return
        from ..services.export_service import suggestions_to_markdown

        text = suggestions_to_markdown(self._suggestions, self._sample.rgb)
        self._save_text(text, "配色建议.md", "Markdown 文件 (*.md)")

    def _export_csv(self) -> None:
        if self._sample is None:
            show_toast(self, "还没有取色", "warn")
            return
        from ..services.export_service import suggestions_to_csv

        text = suggestions_to_csv(self._suggestions, self._sample.rgb)
        self._save_text(text, "配色建议.csv", "CSV 文件 (*.csv)")

    def _copy_share_text(self) -> None:
        """一键把「目标色 + 前两套配比」复制成纯文本，便于发群/发帖。"""
        if self._sample is None:
            show_toast(self, "还没有取色", "warn")
            return
        from ..services.export_service import suggestions_to_share_text

        text = suggestions_to_share_text(
            self._suggestions, self._sample.rgb,
            title=f"涂装配色：{self._sample.hex}",
        )
        if copy_to_clipboard(text):
            show_toast(self, "分享文本已复制", "success")
        else:
            show_toast(self, "复制失败", "error")

    def _save_text(self, text: str, default_name: str, pattern: str) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(self, "导出", default_name, pattern)
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(text)
            show_toast(self, f"已导出到 {path}", "success")
        except OSError as exc:
            logger.error("导出失败: %s", exc)
            show_toast(self, f"导出失败：{exc}", "error")

    @staticmethod
    def _show_about() -> None:
        from PySide6.QtWidgets import QMessageBox

        from .. import __version__
        from ..data.paint_db import get_database

        db = get_database()
        QMessageBox.information(
            None, "关于",
            f"ModelPaintPal v{__version__}\n\n"
            f"3D 打印模型涂装配色助手\n"
            f"色号库：{len(db)} 条 / {len(db.brands)} 个品牌\n\n"
            "色值为基于官方色卡的屏幕近似值，用于相对匹配与配比估算；\n"
            "正式喷涂前请务必小量试喷确认。",
        )

    # ================================================================== 校准
    def _on_calibrate_requested(self, suggestion) -> None:
        anchor = suggestion.anchor
        value, ok = QInputDialog.getText(
            self, "校准色值",
            f"输入 {anchor.full_label} {anchor.name} 的实测色值（#RRGGBB）：",
            text=anchor.hex,
        )
        if not ok or not value.strip():
            return
        if calibrate(anchor.uid, value.strip()):
            self._db = get_database(force=True)
            self._matcher = PaintMatcher(self._db)
            self._compute_now()
            self._settings_panel.sync_from_config()
            self._refresh_db_label()
            show_toast(self, f"已校准 {anchor.code} → {value.strip().upper()}", "success")
        else:
            show_toast(self, "色值格式不正确，应为 #RRGGBB", "error")

    # ============================================================ 联网核实
    def _on_verify_requested(self, suggestion) -> None:
        """发起一次核实。网络部分在工作线程里跑，主线程不等待。"""
        anchor = suggestion.anchor
        enabled = bool(getattr(self._config, "check_updates_on_start", False))
        dialog = VerifyDialog(self, on_adopt=self._on_adopt_verified)
        dialog.set_report(self._pending_report(anchor, enabled))
        submit_verify(
            anchor,
            enabled=enabled,
            timeout=3.0,
            on_done=dialog.set_report,
            on_error=lambda message: dialog.set_report(
                self._failed_report(anchor, message)),
        )
        dialog.exec()

    def _pending_report(self, anchor, enabled: bool):
        """等待期间先显示「查询中」，不要弹出一个空白框。"""
        report = VerifyReport(
            uid=anchor.uid, code=anchor.code, brand_key=anchor.brand_key,
            local_hex=anchor.hex,
            local_source=(anchor.source.name if anchor.source else ""),
            local_date=anchor.src_date,
        )
        report.configured = enabled
        report.note = "查询中…"
        return report

    def _failed_report(self, anchor, message: str):
        report = self._pending_report(anchor, True)
        report.configured = False
        report.note = f"核实过程出错：{message}"
        return report

    def _on_adopt_verified(self, report, hex_value: str) -> None:
        """用户确认采用核实值 —— 走既有的校准回路写入。"""
        if adopt(report.uid, hex_value):
            self._on_database_changed()
            self._settings_panel.sync_from_config()
            show_toast(self, f"已采用 {report.code} → {hex_value}", "success")
        else:
            show_toast(self, "色值格式不正确，未写入", "error")

    def _on_database_changed(self) -> None:
        self._db = get_database(force=True)
        self._matcher = PaintMatcher(self._db)
        self._compute_now()
        self._request_mix_compute()
        self._refresh_db_label()

    def _refresh_db_label(self) -> None:
        db = get_database()
        self._db_label.setText(f"色号库 {len(db)} 条 / {len(db.brands)} 品牌")

    # ================================================================== 收藏/历史
    def _favorite_current(self) -> None:
        if self._sample is None:
            show_toast(self, "还没有取色", "warn")
            return
        self._favorites.add(SampleRecord(rgb=self._sample.rgb, source=self._sample.source))
        self._refresh_library()
        show_toast(self, f"已收藏 {self._sample.hex}", "success")

    def _on_library_color_selected(self, record: SampleRecord) -> None:
        self._apply_color(record.rgb, source=record.source, remember=False)
        self._update_status(f"已载入 {record.hex}")

    def _on_history_removed(self, uid: str) -> None:
        self._history.remove(uid)
        self._refresh_library()

    def _on_favorite_removed(self, uid: str) -> None:
        self._favorites.remove(uid)
        self._refresh_library()

    def _on_favorite_added(self, record: SampleRecord) -> None:
        self._favorites.add(record)
        self._refresh_library()
        show_toast(self, f"已收藏 {record.hex}", "success")

    def _on_history_cleared(self) -> None:
        self._history.clear()
        self._refresh_library()

    def _on_favorites_cleared(self) -> None:
        self._favorites.clear()
        self._refresh_library()

    def _refresh_library(self) -> None:
        self._history.limit = self._config.history_limit
        self._favorites.limit = self._config.favorites_limit
        self._library.set_history(self._history.recent(60))
        self._library.set_favorites(self._favorites.all())

    # ================================================================== 设置联动
    def _on_brand_filter_changed(self, brands: List[str]) -> None:
        self._brand_filter = list(brands)
        # 空列表 = 不限品牌，也要落盘，否则下次启动会与界面上显示的范围不一致
        self._config.preferred_brands = list(brands)
        save_config(self._config)
        self._request_compute(immediate=True)
        self._request_mix_compute()
        scope = "全部品牌" if not brands else f"{len(brands)} 个品牌"
        self._update_status(f"建议范围已切换为{scope}")

    def _on_formula_changed(self, formula: str) -> None:
        self._config.delta_e_formula = formula
        save_config(self._config)
        self._request_compute(immediate=True)

    def _on_settings_changed(self) -> None:
        """设置页改了容差/条数/模型等：立刻重算，避免"改完没生效"。"""
        self._request_compute(immediate=True)
        self._request_mix_compute()
        self._update_status("设置已保存，配色建议已重新计算")

    def _on_coverage_changed(self) -> None:
        save_config(self._config)
        self._request_compute(immediate=False)
        self._request_mix_compute()

    # ================================================================== 热键
    def _apply_hotkeys(self) -> None:
        bindings = []
        if self._config.pick_hotkey:
            bindings.append((_HOTKEY_PICK, self._config.pick_hotkey))
        if self._config.copy_hex_hotkey:
            bindings.append((_HOTKEY_COPY, self._config.copy_hex_hotkey))
        self._hotkeys.set_bindings(bindings)
        self._hotkeys.start()
        self._pick_panel.set_hotkey_hint(
            f"热键 {self._config.pick_hotkey or '—'} 吸色 · "
            f"{self._config.copy_hex_hotkey or '—'} 复制 HEX"
        )

    def _on_hotkey_triggered(self, name: str) -> None:
        if name == _HOTKEY_PICK:
            self._start_picking()
        elif name == _HOTKEY_COPY:
            if self._sample is not None:
                copy_to_clipboard(self._sample.hex)
                self._update_status(f"已复制 {self._sample.hex}")
            else:
                self._update_status("还没有取色，无法复制")

    def _on_hotkey_failed(self, name: str, reason: str) -> None:
        logger.warning("热键 %s 注册失败: %s", name, reason)
        self._update_status(reason)
        show_toast(self, reason, "warn", 4200)

    # ================================================================== 引导
    def _start_onboarding(self) -> None:
        self._onboarding.set_steps(self._build_onboarding_steps())
        self._onboarding.start()

    def _on_onboarding_done(self) -> None:
        if self._config.show_onboarding:
            self._config.show_onboarding = False
            save_config(self._config)
            self._settings_panel.sync_from_config()

    # ================================================================== 其它
    def _update_status(self, message: str) -> None:
        self.statusBar().showMessage(message, 6000)

    def export_report(self) -> str:
        """导出当前建议为 JSON（供菜单/自动化测试使用）。"""
        if self._sample is None:
            return "{}"
        return suggestions_to_json(self._suggestions, self._sample.rgb)

    def showEvent(self, event) -> None:  # noqa: N802
        """首次显示时按真实窗口宽度分配左右栏（左栏 320–380，占 28%）。"""
        if not getattr(self, "_splitter_sized", False):
            self._splitter_sized = True
            width = self.width()
            left = max(320, min(380, int(width * 0.28)))
            self._splitter.setSizes([left, max(480, width - left)])
        super().showEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        # 先作废在途的异步计算：把 token 推到新值，之后任何迟到的结果都会被
        # ``_on_suggest_ready`` 丢掉，避免向正在销毁的窗口投递信号。
        self._suggest_token += 1
        self._compute_timer.stop()
        self._config.window_width = self.width()
        self._config.window_height = self.height()
        save_config(self._config)
        self._picker.stop()
        self._hotkeys.stop()
        # 等线程池里最后一次配色计算收尾（通常 <200ms），再让窗口真正销毁，
        # 否则 PySide6 在解释器退出时可能因后台仍持有 Qt 对象而硬崩。
        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().waitForDone(3000)
        super().closeEvent(event)
