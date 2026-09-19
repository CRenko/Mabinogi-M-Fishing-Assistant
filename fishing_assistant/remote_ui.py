"""Desktop activation and phone pairing, independent of fishing controls."""
import threading
import time
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFrame, QHBoxLayout,
                              QLabel, QLineEdit, QPushButton, QVBoxLayout)
from .remote import OFFICIAL_RELAY_URL, RemoteError, RemoteReporter

class RemotePanel(QFrame):
    completed = Signal(object)

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine, self.reporter, self.busy = engine, RemoteReporter(), False
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(10)
        title = QLabel("手机远程查看（实验性）")
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        hint = QLabel("只上报运行、校准和停止原因，不上传画面、聊天或原始日志。约每分钟同步；关闭后不影响本地钓鱼。")
        hint.setWordWrap(True)
        hint.setObjectName("helper")
        layout.addWidget(hint)
        self.custom = QCheckBox("使用自建中转")
        layout.addWidget(self.custom)
        self.address = QLineEdit()
        self.address.setPlaceholderText("https://你的中转地址")
        self.address.setMaxLength(240)
        layout.addWidget(self.address)
        self.source_hint = QLabel()
        self.source_hint.setObjectName("helper")
        self.source_hint.setWordWrap(True)
        layout.addWidget(self.source_hint)
        self.test_button = QPushButton("测试中转连接")
        self.test_button.clicked.connect(self._probe)
        layout.addWidget(self.test_button)
        self.code = QLineEdit()
        self.code.setPlaceholderText("输入中转管理员提供的激活码")
        self.code.setEchoMode(QLineEdit.EchoMode.Password)
        self.code.setMaxLength(64)
        layout.addWidget(self.code)
        self.activate_button = QPushButton("激活当前电脑")
        self.activate_button.clicked.connect(self._activate)
        layout.addWidget(self.activate_button)
        self.bound_info = QLabel()
        self.bound_info.setObjectName("helper")
        self.bound_info.setWordWrap(True)
        self.bound_info.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.bound_info)
        self.enabled = QCheckBox("启用远程状态上报")
        self.enabled.toggled.connect(self._enable)
        layout.addWidget(self.enabled)
        actions = QHBoxLayout()
        self.pair_button = QPushButton("生成手机配对二维码")
        self.unpair_button = QPushButton("解除手机绑定")
        self.pair_button.clicked.connect(self._pair)
        self.unpair_button.clicked.connect(self._unpair)
        actions.addWidget(self.pair_button)
        actions.addWidget(self.unpair_button)
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("helper")
        layout.addWidget(self.status)
        saved = self.reporter.config()
        self.custom.setChecked(saved.get("source") == "custom")
        self.address.setText(saved.get("relay", OFFICIAL_RELAY_URL))
        self.custom.toggled.connect(self._source)
        self.completed.connect(self._completed)
        self._source()
        self._sync()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self._tick()

    def set_theme(self, theme):
        day = theme == "day"
        background, border, foreground = ("#EDF1F5", "#DCE3EA", "#8A98A8") if day else ("#0C1624", "#223047", "#60748D")
        base = "#FFFFFF" if day else "#0B1626"
        self.setStyleSheet(
            f"QPushButton:disabled, QLineEdit:disabled {{ background: {background}; border-color: {border}; color: {foreground}; }}"
            f"QCheckBox:disabled {{ color: {foreground}; }}"
            f"QCheckBox::indicator:unchecked {{ background: {base}; border-color: {border}; }}"
        )

    def _probe_result(self, message):
        self.reporter.connection_message = message

    def _probe(self):
        relay = self.address.text()
        self._work(lambda: self.reporter.probe(relay), self._probe_result)

    def _source(self):
        custom = self.custom.isChecked()
        self.address.setEnabled(custom and not self.busy)
        if not custom:
            self.address.setText(OFFICIAL_RELAY_URL)
        self.source_hint.setText("自建中转由其管理员发码；切换地址需重新激活，旧绑定不会迁移。" if custom else
            ("官方试验名额由激活码管理，一码绑定一台电脑。" if OFFICIAL_RELAY_URL else "官方中转尚未部署，可先使用自建中转测试。"))
        self._sync()

    def _sync(self):
        config = self.reporter.config()
        self.enabled.blockSignals(True)
        self.enabled.setChecked(bool(config.get("enabled")))
        self.enabled.blockSignals(False)
        for control in (self.pair_button, self.unpair_button, self.enabled):
            control.setEnabled(bool(config.get("device_id")) and not self.busy)
        for control in (self.activate_button, self.custom, self.code):
            control.setEnabled(not self.busy)
        available = not self.busy and (self.custom.isChecked() or bool(OFFICIAL_RELAY_URL))
        self.activate_button.setEnabled(available)
        self.test_button.setEnabled(available)
        self.bound_info.setText("当前已激活中转：" + config.get("relay", "") if config.get("device_id") else "尚未激活中转；本地钓鱼可正常使用。")
        self.address.setEnabled(not self.busy and self.custom.isChecked())

    def _tick(self):
        self.reporter.sample(self.engine.config(), self.engine.is_monitoring())
        if not self.busy:
            self.status.setText(self.reporter.connection_message)

    def _confirm(self, text, action="继续"):
        dialog = QDialog(self)
        dialog.setObjectName("updateDialog")
        dialog.setWindowTitle("远程查看")
        dialog.setFixedWidth(400)
        layout = QVBoxLayout(dialog)
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
        row = QHBoxLayout()
        cancel, ok = QPushButton("取消"), QPushButton(action)
        cancel.clicked.connect(dialog.reject)
        ok.clicked.connect(dialog.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        layout.addLayout(row)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _work(self, operation, callback=None):
        if self.busy:
            return
        self.busy = True
        self.status.setText("正在连接中转…")
        self._sync()
        def run():
            try:
                result = (True, operation(), callback)
            except Exception as error:
                result = (False, str(error) if isinstance(error, RemoteError) else "操作失败，请稍后再试。", None)
            try:
                self.completed.emit(result)
            except RuntimeError:
                pass
        threading.Thread(target=run, name="remote-pairing", daemon=True).start()

    def _completed(self, result):
        success, value, callback = result
        self.busy = False
        self._sync()
        self.reporter.connection_message = "操作完成" if success else value
        if success and callback:
            callback(value)
        self._tick()

    def _activate(self):
        if self.reporter.config().get("device_id") and not self._confirm(
            "重新激活会关闭当前上报。旧中转的手机绑定需先解除，激活码也可能无法再次使用。确定继续？"):
            return
        relay, code = self.address.text(), self.code.text()
        source = "custom" if self.custom.isChecked() else "official"
        self.code.clear()
        self._work(lambda: self.reporter.activate(relay, code, source))

    def _enable(self, enabled):
        if enabled and not self._confirm("将运行状态、校准、模式、版本和停止原因发送到所选中转。\n不发送截图或原始日志。是否启用？", "启用"):
            self._sync()
            return
        try:
            self.reporter.set_enabled(enabled)
        except Exception:
            self.reporter.connection_message = "无法保存远程设置，请检查权限。"
        self._sync()
        self._tick()

    def _pair(self):
        if self._confirm("生成新二维码会立即解除此前手机的访问权限。二维码 10 分钟内有效，只能绑定一部手机，请勿公开。", "生成二维码"):
            self._work(self.reporter.pair, self._show_pair)

    def _unpair(self):
        if self._confirm("原手机将无法查看这台电脑的状态。本地钓鱼和上报不受影响。", "解除绑定"):
            self._work(self.reporter.unpair)

    def _show_pair(self, result):
        link, expires_at = result
        dialog = QDialog(self)
        dialog.setObjectName("updateDialog")
        dialog.setWindowTitle("绑定手机")
        dialog.setFixedWidth(400)
        layout = QVBoxLayout(dialog)
        label = QLabel("用手机端扫描二维码，再确认是否记住此设备。")
        label.setWordWrap(True)
        layout.addWidget(label)
        qr_label = QLabel()
        qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(qr_label)
        try:
            import qrcode
            qr = qrcode.QRCode(box_size=4, border=4)
            qr.add_data(link)
            qr.make(fit=True)
            matrix = qr.get_matrix()
            pixel = max(1, 300 // len(matrix))
            size = len(matrix) * pixel
            canvas = QImage(size, size, QImage.Format.Format_RGB32)
            canvas.fill(Qt.GlobalColor.white)
            painter = QPainter(canvas)
            for y, row in enumerate(matrix):
                for x, black in enumerate(row):
                    if black:
                        painter.fillRect(x * pixel, y * pixel, pixel, pixel, Qt.GlobalColor.black)
            painter.end()
            qr_label.setPixmap(QPixmap.fromImage(canvas))
        except ImportError:
            qr_label.setText("二维码组件未安装，可复制链接配对。")
        countdown = QLabel()
        countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(countdown)
        copy = QPushButton("复制配对链接")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(link))
        layout.addWidget(copy)
        done = QPushButton("关闭")
        done.clicked.connect(dialog.accept)
        layout.addWidget(done)
        timer = QTimer(dialog)
        def tick():
            left = max(0, int(expires_at - time.time()))
            countdown.setText(f"剩余 {left // 60:02d}:{left % 60:02d}" if left else "二维码已过期，请重新生成")
            if not left:
                qr_label.clear()
                copy.setEnabled(False)
        tick()
        timer.timeout.connect(tick)
        timer.start(1000)
        dialog.exec()
        if QApplication.clipboard().text() == link:
            QApplication.clipboard().clear()

    def shutdown(self):
        self.timer.stop()
        self.reporter.close()
