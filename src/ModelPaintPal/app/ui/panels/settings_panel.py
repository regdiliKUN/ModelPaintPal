# -*- coding: utf-8 -*-
"""设置面板。所有选项即时写入 ``AppConfig`` 并落地到用户目录。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ...core.config import AppConfig, save_config
from ...core.delta_e import available_formulas
from ...core.paths import USER_DATA_DIR
from ...data.paint_db import calibration_map, get_database, reset_calibration
from ...services.mixing import MIXING_MODELS, describe_model
from ..widgets.form_row import form_label, hint_label, with_hint

__all__ = ["SettingsPanel"]

# 热键输入去抖：足够长到能输完一个组合键，又不至于让人以为没生效
_HOTKEY_DEBOUNCE_MS = 400

_FIELD_WIDTH = 200


def _section(parent: QWidget, title: str) -> QFormLayout:
    card = QFrame(parent)
    card.setObjectName("Card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 10, 14, 12)
    layout.setSpacing(8)
    label = QLabel(title)
    label.setObjectName("SectionLabel")
    layout.addWidget(label)
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
    form.setHorizontalSpacing(12)
    form.setVerticalSpacing(10)
    form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
    layout.addLayout(form)
    parent.layout().addWidget(card)
    return form


class SettingsPanel(QFrame):
    """设置页。"""

    hotkeysChanged = Signal()
    onboardingRequested = Signal()
    databaseChanged = Signal()
    settingsChanged = Signal()     # 影响配色结果的项（容差/条数/模型/混色许可）
    # 请求把配置落盘。**不在这里直接 save_config**：save_config 是原子写 + fsync
    # （实测 3.8 ms/次），而本页 8 个数值控件都是逐格触发 valueChanged，
    # 拖一次滑块就是十几次写盘。落盘时机交给主窗口去抖。
    persistRequested = Signal()

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._hotkey_timer = QTimer(self)
        self._hotkey_timer.setSingleShot(True)
        self._hotkey_timer.setInterval(_HOTKEY_DEBOUNCE_MS)
        self._hotkey_timer.timeout.connect(self._commit_hotkeys)

        self._updating = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 6, 0)
        container_layout.setSpacing(10)
        container.setLayout(container_layout)
        scroll.setWidget(container)
        outer.addWidget(scroll)
        self._container_layout = container_layout

        self._build_picker_section(container)
        self._build_match_section(container)
        self._build_data_section(container)
        self._build_misc_section(container)
        container_layout.addStretch(1)

        self._updating = False
        self._last_match_sig = self._match_signature()
        # 构造完立刻与真实配置对齐：此前这里漏了同步，控件停在各 SpinBox 的最小值，
        # 用户一动任意开关就会把「6 条建议 / 3 组分 / ΔE 3.0」写成「1 条 / 1 组分 / 0.2」。
        self.sync_from_config()

    # ------------------------------------------------------------------ 分组
    def _build_picker_section(self, container: QWidget) -> None:
        form = _section(container, "取色")
        self._zoom = QSpinBox()
        self._zoom.setRange(2, 40)
        self._zoom.setSuffix(" ×")
        self._zoom.setMaximumWidth(_FIELD_WIDTH)
        self._zoom.valueChanged.connect(self._commit)
        form.addRow(form_label("放大镜倍率"), with_hint(
            self._zoom, "吸色时跟随光标的放大镜倍数，2–40×"))

        self._grid = QSpinBox()
        self._grid.setRange(3, 41)
        self._grid.setSingleStep(2)
        self._grid.setSuffix(" px")
        self._grid.setMaximumWidth(_FIELD_WIDTH)
        self._grid.valueChanged.connect(self._commit)
        form.addRow(form_label("取样区域"), with_hint(
            self._grid, "放大镜一次读取的像素边长（会自动取奇数）"))

        self._average = QSpinBox()
        self._average.setRange(1, 9)
        self._average.setSingleStep(2)
        self._average.setMaximumWidth(_FIELD_WIDTH)
        self._average.valueChanged.connect(self._commit)
        form.addRow(form_label("中心平均"), with_hint(
            self._average, "3/5 = 取中心 3×3、5×5 像素平均"))

        self._follow = QCheckBox("放大镜跟随光标")
        self._follow.stateChanged.connect(self._commit)
        form.addRow("", self._follow)

        self._auto_copy = QCheckBox("取色后自动复制 HEX")
        self._auto_copy.stateChanged.connect(self._commit)
        form.addRow("", self._auto_copy)

        self._pick_hotkey = QLineEdit()
        self._pick_hotkey.setMaximumWidth(_FIELD_WIDTH)
        self._pick_hotkey.setToolTip("格式如 Ctrl+Shift+X；留空表示不注册全局热键")
        self._pick_hotkey.textChanged.connect(self._on_hotkey_changed)
        form.addRow(form_label("吸色热键"), with_hint(
            self._pick_hotkey, "格式如 Ctrl+Shift+X；留空则不注册全局热键"))

        self._copy_hotkey = QLineEdit()
        self._copy_hotkey.setMaximumWidth(_FIELD_WIDTH)
        self._copy_hotkey.textChanged.connect(self._on_hotkey_changed)
        form.addRow(form_label("复制热键"), self._copy_hotkey)

        hint = hint_label("热键通过 Windows RegisterHotKey 注册；"
                          "若与其它软件冲突会注册失败并在状态栏提示。", container)
        form.addRow("", hint)

    def _build_match_section(self, container: QWidget) -> None:
        form = _section(container, "配色建议")
        self._formula = QComboBox()
        self._formula.addItems(list(available_formulas()))
        self._formula.setMaximumWidth(_FIELD_WIDTH + 40)
        self._formula.currentTextChanged.connect(self._commit)
        form.addRow(form_label("色差公式"), with_hint(
            self._formula, "CIEDE2000 是工业标准；CIE76 更快但蓝紫区偏乐观"))

        self._tolerance = QDoubleSpinBox()
        self._tolerance.setRange(0.2, 20.0)
        self._tolerance.setDecimals(1)
        self._tolerance.setSingleStep(0.5)
        self._tolerance.setMaximumWidth(_FIELD_WIDTH)
        self._tolerance.valueChanged.connect(self._commit)
        form.addRow(form_label("直用容差 ΔE"), with_hint(
            self._tolerance, "低于该值判为「可直接瓶用」，默认 3.0"))

        self._max_suggestions = QSpinBox()
        self._max_suggestions.setRange(1, 12)
        self._max_suggestions.setMaximumWidth(_FIELD_WIDTH)
        self._max_suggestions.valueChanged.connect(self._commit)
        form.addRow(form_label("建议条数"), self._max_suggestions)

        self._model = QComboBox()
        for key in MIXING_MODELS:
            self._model.addItem(describe_model(key), key)
        self._model.setMaximumWidth(_FIELD_WIDTH + 180)
        self._model.currentIndexChanged.connect(self._commit)
        form.addRow(form_label("混合模型"), self._model)

        self._max_components = QSpinBox()
        self._max_components.setRange(1, 3)
        self._max_components.setMaximumWidth(_FIELD_WIDTH)
        self._max_components.valueChanged.connect(self._commit)
        form.addRow(form_label("最多组分"), with_hint(
            self._max_components, "1 = 只找现成色号；3 = 允许三色调配（计算更慢）"))

        self._drop_total = QSpinBox()
        self._drop_total.setRange(4, 200)
        self._drop_total.setSuffix(" 滴")
        self._drop_total.setMaximumWidth(_FIELD_WIDTH)
        self._drop_total.valueChanged.connect(self._commit)
        form.addRow(form_label("配比基准总量"), with_hint(
            self._drop_total, "实际配方的总滴数；颜色、百分比及用量按取整后的滴数同步计算"))

        self._allow_cross_brand = QCheckBox("允许跨产品线混配（兼容性未验证）")
        self._allow_cross_brand.stateChanged.connect(self._commit)
        form.addRow("", self._allow_cross_brand)

        self._allow_metal = QCheckBox("允许金属漆/珠光漆参与调配")
        self._allow_metal.stateChanged.connect(self._commit)
        form.addRow("", self._allow_metal)

        self._allow_clear = QCheckBox("允许透明漆/荧光漆参与调配")
        self._allow_clear.stateChanged.connect(self._commit)
        form.addRow("", self._allow_clear)

    def _build_data_section(self, container: QWidget) -> None:
        form = _section(container, "色号库")
        db = get_database()
        stats = QLabel(f"共 {len(db)} 条色号，覆盖 {len(db.brands)} 个品牌")
        stats.setObjectName("DimLabel")
        form.addRow(form_label("规模"), stats)

        self._calibration = QLabel("")
        self._calibration.setWordWrap(True)
        self._calibration.setObjectName("DimLabel")
        form.addRow(form_label("我的校准"), self._calibration)

        row = QHBoxLayout()
        reset_one = QPushButton("清除全部校准")
        reset_one.setObjectName("GhostButton")
        reset_one.clicked.connect(self._reset_calibration)
        row.addWidget(reset_one)
        form.addRow("", self._wrap(row, container))

        tip = QLabel("色值为基于官方色卡的屏幕近似值，用于相对匹配。"
                     "若你试喷后发现偏差，可在建议卡片上点「校准色值」覆盖。")
        tip.setWordWrap(True)
        tip.setObjectName("FaintLabel")
        form.addRow("", tip)

    def _build_misc_section(self, container: QWidget) -> None:
        form = _section(container, "其它")
        self._history_limit = QSpinBox()
        self._history_limit.setRange(10, 2000)
        self._history_limit.setMaximumWidth(_FIELD_WIDTH)
        self._history_limit.valueChanged.connect(self._commit)
        form.addRow(form_label("历史保留条数"), self._history_limit)

        self._show_onboarding = QCheckBox("启动时显示新手引导")
        self._show_onboarding.stateChanged.connect(self._commit)
        form.addRow("", self._show_onboarding)

        # 联网总开关。默认关闭，且说明里必须写清楚只发文本 —— 这个应用会抓全屏
        # 取色，用户看到「联网」第一反应就是屏幕会不会被传走。
        self._allow_online = QCheckBox("允许联网核实色号来源（默认关闭）")
        self._allow_online.setToolTip(
            "开启后，「核实来源」会向已配置的核验源查询色号。"
            "仅发送品牌与色号文本，绝不发送图像或屏幕内容。")
        self._allow_online.stateChanged.connect(self._commit)
        form.addRow("", self._allow_online)

        self._online_hint = QLabel(
            "仅发送「品牌 + 色号」文本，不发送任何图像；结果只展示，不自动改动本地数据。")
        self._online_hint.setObjectName("FaintLabel")
        self._online_hint.setWordWrap(True)
        form.addRow("", self._online_hint)

        row = QHBoxLayout()
        open_dir = QPushButton("打开数据目录")
        open_dir.setObjectName("GhostButton")
        open_dir.clicked.connect(self._open_data_dir)
        show_guide = QPushButton("重看新手引导")
        show_guide.setObjectName("GhostButton")
        show_guide.clicked.connect(self.onboardingRequested.emit)
        restore = QPushButton("恢复默认设置")
        restore.setObjectName("GhostButton")
        restore.setToolTip("把本页所有参数恢复为出厂默认值（不影响历史、收藏与色号校准）")
        restore.clicked.connect(self._on_restore_defaults)
        row.addWidget(open_dir)
        row.addWidget(show_guide)
        row.addWidget(restore)
        row.addStretch(1)
        form.addRow("", self._wrap(row, container))

    @staticmethod
    def _wrap(layout: QHBoxLayout, parent: QWidget) -> QWidget:
        widget = QWidget(parent)
        widget.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        return widget

    # ------------------------------------------------------------------ 签名
    def _match_signature(self) -> tuple:
        """只包含会改变配色结果的字段。

        历史条数、放大镜倍率这类设置跟匹配无关，改它们不该触发一次 140 ms 的重算。
        """
        cfg = self._config
        return (
            cfg.delta_e_formula, round(float(cfg.match_tolerance), 3),
            int(cfg.max_suggestions), cfg.mixing_model,
            int(cfg.max_recipe_components), int(cfg.drop_total),
            bool(cfg.allow_metallic_in_mix), bool(cfg.allow_clear_in_mix),
            bool(cfg.allow_cross_brand_mix),
        )

    # ------------------------------------------------------------------ 同步
    def sync_from_config(self) -> None:
        """按配置回填全部控件。

        ``_updating`` 必须用 try/finally 复位：这里是十几个 setValue/setChecked，
        任何一个抛异常（比如校准记录文件坏了）都会让 ``_updating`` 永久停在 True，
        之后用户改这个页面上的**任何**设置都会被 ``_commit`` 静默丢弃——
        界面还在，但设置不再生效，而且没有任何提示。
        """
        self._updating = True
        try:
            self._sync_widgets()
        finally:
            self._updating = False

    def _sync_widgets(self) -> None:
        cfg = self._config
        self._zoom.setValue(cfg.magnifier_zoom)
        self._grid.setValue(cfg.magnifier_grid)
        self._average.setValue(cfg.sample_average)
        self._follow.setChecked(cfg.magnifier_follow)
        self._auto_copy.setChecked(cfg.auto_copy_on_pick)
        self._pick_hotkey.setText(cfg.pick_hotkey)
        self._copy_hotkey.setText(cfg.copy_hex_hotkey)
        self._formula.setCurrentText(cfg.delta_e_formula)
        self._tolerance.setValue(cfg.match_tolerance)
        self._max_suggestions.setValue(cfg.max_suggestions)
        self._model.setCurrentIndex(max(0, self._model.findData(cfg.mixing_model)))
        self._max_components.setValue(cfg.max_recipe_components)
        self._drop_total.setValue(cfg.drop_total)
        self._allow_metal.setChecked(cfg.allow_metallic_in_mix)
        self._allow_clear.setChecked(cfg.allow_clear_in_mix)
        self._allow_cross_brand.setChecked(cfg.allow_cross_brand_mix)
        self._history_limit.setValue(cfg.history_limit)
        self._show_onboarding.setChecked(cfg.show_onboarding)
        self._allow_online.setChecked(bool(getattr(cfg, "check_updates_on_start", False)))
        self._refresh_calibration()
        self._last_match_sig = self._match_signature()

    def _refresh_calibration(self) -> None:
        mapping = calibration_map()
        if not mapping:
            self._calibration.setText("尚未校准任何色号")
            return
        self._calibration.setText("\n".join(
            f"{uid.split(':')[-1]} → {value}" for uid, value in list(mapping.items())[:12]
        ))

    def _commit_hotkeys(self) -> None:
        """热键输入停手后：落盘并让主窗口重新注册。"""
        self.persistRequested.emit()
        self.hotkeysChanged.emit()

    # ------------------------------------------------------------------ 提交
    def _commit(self) -> None:
        if self._updating:
            return
        cfg = self._config
        cfg.magnifier_zoom = self._zoom.value()
        cfg.magnifier_grid = self._grid.value()
        cfg.sample_average = self._average.value()
        cfg.magnifier_follow = self._follow.isChecked()
        cfg.auto_copy_on_pick = self._auto_copy.isChecked()
        cfg.delta_e_formula = self._formula.currentText()
        cfg.match_tolerance = self._tolerance.value()
        cfg.max_suggestions = self._max_suggestions.value()
        cfg.mixing_model = self._model.currentData() or "kubelka_munk"
        cfg.max_recipe_components = self._max_components.value()
        cfg.drop_total = self._drop_total.value()
        cfg.allow_metallic_in_mix = self._allow_metal.isChecked()
        cfg.allow_clear_in_mix = self._allow_clear.isChecked()
        cfg.allow_cross_brand_mix = self._allow_cross_brand.isChecked()
        cfg.history_limit = self._history_limit.value()
        cfg.show_onboarding = self._show_onboarding.isChecked()
        cfg.check_updates_on_start = self._allow_online.isChecked()
        cfg.validate()
        self.persistRequested.emit()
        # 容差/条数/模型/混色许可会改变匹配结果，必须让主窗口重算，
        # 否则用户改完设置回到建议页会看到"没生效"的旧结果。
        signature = self._match_signature()
        if signature != self._last_match_sig:
            self._last_match_sig = signature
            self.settingsChanged.emit()

    def _on_restore_defaults(self) -> None:
        """把配置恢复出厂值（历史/收藏/校准不动）。"""
        self._config.reset_to_defaults()
        self._config.validate()
        save_config(self._config)
        self.sync_from_config()
        self.settingsChanged.emit()
        self.hotkeysChanged.emit()

    def _on_hotkey_changed(self) -> None:
        """热键输入框是 textChanged，逐字符触发。

        直接落盘 + 重新注册热键的话，输入 "Ctrl+Shift+X" 会写 12 次盘、
        并 12 次注销/重注册 Win32 热键（每次都要停线程）。这里等用户停手再说。
        """
        if self._updating:
            return
        self._config.pick_hotkey = self._pick_hotkey.text().strip()
        self._config.copy_hex_hotkey = self._copy_hotkey.text().strip()
        self._hotkey_timer.start()

    def _reset_calibration(self) -> None:
        if reset_calibration():
            self._refresh_calibration()
            self.databaseChanged.emit()

    @staticmethod
    def _open_data_dir() -> None:
        path = Path(USER_DATA_DIR)
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError:
            pass
