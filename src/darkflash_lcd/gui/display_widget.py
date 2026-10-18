from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget


class DisplayWidget(QWidget):
    """Draws what the pump LCD shows: 88.8°C, two round % fields, 8888MHZ, cyan ring."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(260, 260)
        self.reading = {"temp_tenths": 0, "left": 0, "right": 0, "bottom": 0}
        self.online = False

    def set_reading(self, reading: dict | None, online: bool) -> None:
        if reading:
            self.reading = reading
        self.online = online
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height()) - 10
        r = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        p.setBrush(QColor("#101215"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(r)
        ring = QColor("#22b8f0" if self.online else "#3a4048")
        pen = QPen(ring, side * 0.035)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(r.adjusted(side * .06, side * .06, -side * .06, -side * .06), 250 * 16, 330 * 16)
        fg = QColor("#eaf6ff" if self.online else "#6b7380")
        p.setPen(fg)
        rd = self.reading
        t = rd["temp_tenths"]
        big = "EE" if t >= 1000 else f"{t // 10:>2}.{t % 10}"
        p.setFont(QFont("DejaVu Sans Mono", int(side * .14), QFont.Bold))
        p.drawText(QRectF(r.x(), r.y() + side * .18, side, side * .2), Qt.AlignCenter, f"{big}°C")
        p.setFont(QFont("DejaVu Sans Mono", int(side * .07), QFont.Bold))
        for i, key in enumerate(("left", "right")):
            cx = r.x() + side * (.33 if i == 0 else .67)
            box = QRectF(cx - side * .13, r.y() + side * .43, side * .26, side * .26)
            p.setPen(QPen(fg, 1.5))
            p.drawEllipse(box)
            p.drawText(box, Qt.AlignCenter, f"{rd[key]}%")
            p.setFont(QFont("DejaVu Sans", int(side * .03)))
            p.drawText(box.adjusted(0, side * .03, 0, 0), Qt.AlignHCenter | Qt.AlignTop,
                       "CPU" if key == "left" else "RAM")
            p.setFont(QFont("DejaVu Sans Mono", int(side * .07), QFont.Bold))
        p.setFont(QFont("DejaVu Sans Mono", int(side * .065)))
        p.drawText(QRectF(r.x(), r.y() + side * .72, side, side * .12), Qt.AlignCenter,
                   f"{rd['bottom']:>4}MHZ")
