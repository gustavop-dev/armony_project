"""Dialogo de configuracion.

El diseno del overlay no incluye pantalla de ajustes, pero hacen falta al menos la
API key y los interruptores que antes vivian en la barra superior (invisibilidad,
modo prueba). Se mantiene aqui, con los colores del overlay.
"""
from PySide6 import QtCore, QtGui, QtWidgets

import theme as T


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        # Sin marco nativo: elimina la barra blanca de titulo del sistema.
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.Dialog)
        self.cfg = dict(cfg)
        self.setMinimumWidth(560)
        self._style()
        self._drag_off = None

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- cabecera propia (arrastrable + boton de cerrar) ---
        header = QtWidgets.QWidget()
        header.setObjectName("dlgHeader")
        hl = QtWidgets.QHBoxLayout(header)
        hl.setContentsMargins(18, 12, 12, 12)
        titulo = QtWidgets.QLabel("Settings")
        tf = titulo.font(); tf.setPixelSize(14); tf.setWeight(QtGui.QFont.DemiBold)
        titulo.setFont(tf)
        titulo.setStyleSheet(f"color: {T.TEXT_BRIGHT};")
        hl.addWidget(titulo)
        hl.addStretch()
        cerrar = QtWidgets.QPushButton("✕")
        cerrar.setCursor(QtCore.Qt.PointingHandCursor)
        cerrar.setFixedSize(26, 26)
        cerrar.setObjectName("closeBtn")
        cerrar.clicked.connect(self.reject)
        hl.addWidget(cerrar)
        outer.addWidget(header)
        self._header = header

        body = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(body)
        form.setContentsMargins(18, 14, 18, 16)
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        form.setSpacing(9)
        outer.addWidget(body)

        form.addRow(self._h("Conexion"))
        self.api = QtWidgets.QLineEdit(cfg.get("anthropic_api_key", ""))
        self.api.setEchoMode(QtWidgets.QLineEdit.Password)
        self.api.setPlaceholderText("sk-ant-...")
        form.addRow("API key de Anthropic:", self.api)

        self.model = QtWidgets.QComboBox()
        self.model.addItems(["claude-haiku-4-5", "claude-opus-4-8", "claude-sonnet-5"])
        self.model.setCurrentText(cfg.get("llm_model", "claude-haiku-4-5"))
        form.addRow("Modelo (latencia vs calidad):", self.model)

        self.wsize = QtWidgets.QComboBox()
        self.wsize.addItems(["tiny", "base", "small", "medium"])
        self.wsize.setCurrentText(cfg.get("whisper_size", "base"))
        form.addRow("Tamano Whisper:", self.wsize)

        self.device = QtWidgets.QComboBox()
        self.device.addItems(["auto", "cpu", "cuda"])
        self.device.setCurrentText(cfg.get("whisper_device", "auto"))
        form.addRow("Dispositivo STT:", self.device)

        self.lang = QtWidgets.QComboBox()
        self.lang.addItems(["es", "en", "auto"])
        self.lang.setCurrentText(cfg.get("language", "es"))
        form.addRow("Idioma:", self.lang)

        form.addRow(self._h("Overlay"))
        self.invis = QtWidgets.QCheckBox("Invisible al compartir pantalla")
        self.invis.setChecked(bool(cfg.get("invisible_on_share", True)))
        form.addRow(self.invis)
        self.test = QtWidgets.QCheckBox("Modo prueba (sin API key, no llama a Claude)")
        self.test.setChecked(bool(cfg.get("test_mode", False)))
        form.addRow(self.test)

        self.opacity = self._spin(cfg.get("window_opacity", 0.30), 0.15, 1.0, 0.05, 2)
        self.opacity.setToolTip("Transparencia del overlay. Bajo = se ve mas lo de detras.")
        form.addRow("Opacidad (0.15–1.0):", self.opacity)

        form.addRow(self._h("Sensibilidad de audio"))
        self.g_sys = self._spin(cfg.get("gain_system", 1.0), 0.5, 10.0, 0.5, 1)
        form.addRow("Ganancia reunion (x):", self.g_sys)
        self.g_mic = self._spin(cfg.get("gain_mic", 1.0), 0.5, 10.0, 0.5, 1)
        form.addRow("Ganancia microfono (x):", self.g_mic)
        self.thresh = self._spin(cfg.get("speech_threshold", 0.012), 0.001, 0.100, 0.002, 3)
        form.addRow("Umbral de voz (menor = mas sensible):", self.thresh)

        self.tmic = QtWidgets.QCheckBox("Transcribir tambien mi voz (contexto para Claude)")
        self.tmic.setChecked(bool(cfg.get("transcribe_mic", True)))
        form.addRow(self.tmic)
        self.echo = QtWidgets.QCheckBox("Ignorar microfono mientras suena la reunion (anti-eco)")
        self.echo.setChecked(bool(cfg.get("mic_echo_gate", True)))
        form.addRow(self.echo)
        self.norm = QtWidgets.QCheckBox("Normalizar cada frase automaticamente")
        self.norm.setChecked(bool(cfg.get("auto_normalize", True)))
        form.addRow(self.norm)

        form.addRow(self._h("Deteccion de frases"))
        self.hang = self._spin(cfg.get("silence_hang", 0.7), 0.3, 2.0, 0.1, 1)
        form.addRow("Pausa de fin de turno (s):", self.hang)
        self.maxutt = self._spin(cfg.get("max_utterance", 8.0), 3.0, 20.0, 1.0, 1)
        form.addRow("Corte de monologo largo (s):", self.maxutt)

        form.addRow(self._h("Coach"))
        self.prompt = QtWidgets.QPlainTextEdit(cfg.get("system_prompt", ""))
        self.prompt.setMinimumHeight(90)
        form.addRow("Prompt del coach:", self.prompt)

        nota = QtWidgets.QLabel("Cambiar modelo o dispositivo requiere detener e iniciar la reunion.")
        nota.setStyleSheet(f"color: {T.TEXT_FAINT}; font-size: 12px;")
        form.addRow(nota)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    # ---------------- arrastre (cabecera sin marco nativo)
    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton and self._header.geometry().contains(e.position().toPoint()):
            self._drag_off = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_off is not None and e.buttons() & QtCore.Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_off)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_off = None

    # ---------------- helpers
    def _h(self, texto):
        lab = QtWidgets.QLabel(texto.upper())
        f = lab.font()
        f.setPixelSize(11)
        f.setWeight(QtGui.QFont.Bold)
        f.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 1.0)
        lab.setFont(f)
        lab.setStyleSheet(f"color: {T.GOLD_LABEL}; margin-top: 8px;")
        return lab

    def _spin(self, valor, minimo, maximo, paso, decimales):
        s = QtWidgets.QDoubleSpinBox()
        s.setRange(minimo, maximo)
        s.setSingleStep(paso)
        s.setDecimals(decimales)
        s.setValue(float(valor))
        return s

    def _style(self):
        self.setStyleSheet(f"""
            QDialog {{ background: #1a1811; border: 1px solid {T.PANEL_BORDER}; }}
            QWidget#dlgHeader {{ background: {T.PANEL_TOP};
                                 border-bottom: 1px solid {T.DIVIDER_SOFT}; }}
            QPushButton#closeBtn {{ background: transparent; border: none;
                                    color: {T.TEXT_DIM}; font-size: 15px; border-radius: 6px; }}
            QPushButton#closeBtn:hover {{ background: {T.BTN_BG_HOVER}; color: {T.TEXT_BRIGHT}; }}
            QLabel {{ color: {T.TEXT_MUTED}; font-size: 13px; }}
            QLineEdit, QComboBox, QDoubleSpinBox, QPlainTextEdit {{
                background: {T.INPUT_BG};
                border: 1px solid {T.BTN_BORDER};
                border-radius: 8px; padding: 6px 9px;
                color: {T.TEXT_BODY}; font-size: 13px;
            }}
            QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {{
                border: 1px solid {T.PANEL_BORDER2};
            }}
            QCheckBox {{ color: {T.TEXT_MUTED}; font-size: 13px; }}
            QPushButton {{
                background: {T.BTN_BG}; border: 1px solid {T.BTN_BORDER};
                border-radius: 8px; padding: 7px 16px; color: {T.TEXT}; font-size: 13px;
            }}
            QPushButton:hover {{ background: {T.BTN_BG_HOVER}; }}
            QPushButton:default {{
                background: {T.GOLD}; color: {T.GOLD_BTN_INK}; border: none; font-weight: 700;
            }}
        """)

    def values(self):
        self.cfg.update({
            "anthropic_api_key": self.api.text().strip(),
            "llm_model": self.model.currentText(),
            "whisper_size": self.wsize.currentText(),
            "whisper_device": self.device.currentText(),
            "language": self.lang.currentText(),
            "invisible_on_share": self.invis.isChecked(),
            "test_mode": self.test.isChecked(),
            "window_opacity": self.opacity.value(),
            "gain_system": self.g_sys.value(),
            "gain_mic": self.g_mic.value(),
            "speech_threshold": self.thresh.value(),
            "transcribe_mic": self.tmic.isChecked(),
            "mic_echo_gate": self.echo.isChecked(),
            "auto_normalize": self.norm.isChecked(),
            "silence_hang": self.hang.value(),
            "max_utterance": self.maxutt.value(),
            "system_prompt": self.prompt.toPlainText(),
        })
        return self.cfg
