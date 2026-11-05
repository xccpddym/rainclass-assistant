"""Application-owned new-question notice, independent of Windows tray banners."""
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel,QPushButton,QApplication

class NewQuestionPopup(QWidget):
    def __init__(self,bottom_offset=0):
        super().__init__(None,Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|
            Qt.WindowType.WindowStaysOnTopHint|Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.bottom_offset=bottom_offset
        self.setFixedWidth(340)
        self.setStyleSheet('NewQuestionPopup {background:#eef6ff;border:2px solid #2878d0;border-radius:8px;} QLabel {color:#102a43;background:transparent;border:0;}')
        layout=QVBoxLayout(self)
        self.title=QLabel();self.title.setTextFormat(Qt.TextFormat.PlainText)
        font=self.title.font();font.setBold(True);self.title.setFont(font);layout.addWidget(self.title)
        self.message=QLabel();self.message.setWordWrap(True);self.message.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.message)
        close=QPushButton('关闭提醒');close.setFocusPolicy(Qt.FocusPolicy.NoFocus);close.clicked.connect(self.hide);layout.addWidget(close)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.hide)

    def show_notice(self,title,message):
        self.title.setText(title);self.message.setText(message);self.adjustSize()
        screen=QApplication.primaryScreen()
        if screen:
            area=screen.availableGeometry();self.move(area.right()-self.width()-16,max(area.top(),area.bottom()-self.height()-16-self.bottom_offset))
        self.show()  # No activateWindow(), raise(), or foreground API.
        self.timer.start(10000)
