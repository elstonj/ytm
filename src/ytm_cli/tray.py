# ytm-cli - YouTube Music CLI
# Created by Jack Elston
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
"""System tray UI for ytm-cli playback with rich media player popup."""

import sys
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QSlider,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ytm_cli.api import YouTubeMusicAPI
from ytm_cli.player import Player

# Catppuccin Mocha palette
_BG = "#1e1e2e"
_SURFACE = "#313244"
_OVERLAY = "#45475a"
_TEXT = "#cdd6f4"
_DIM_TEXT = "#a6adc8"
_ACCENT = "#cba6f7"
_BLUE = "#89b4fa"
_GREEN = "#a6e3a1"
_RED = "#f38ba8"

_NOW_PLAYING_FILE = Path.home() / ".config" / "ytm-cli" / "now_playing"


def _write_now_playing(text: str) -> None:
    """Write current track info for status bar consumption."""
    try:
        _NOW_PLAYING_FILE.parent.mkdir(parents=True, exist_ok=True)
        _NOW_PLAYING_FILE.write_text(text)
    except OSError:
        pass


def _clear_now_playing() -> None:
    """Remove the now_playing file."""
    try:
        _NOW_PLAYING_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _format_time(seconds: float) -> str:
    """Format seconds as MM:SS."""
    if seconds <= 0:
        return "0:00"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"


def _make_fallback_icon() -> QIcon:
    """Create a simple colored circle icon as fallback."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(220, 50, 50))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, 56, 56)
    painter.setBrush(QColor(255, 255, 255))
    triangle = QPolygonF([QPointF(24, 16), QPointF(24, 48), QPointF(48, 32)])
    painter.drawPolygon(triangle)
    painter.end()
    return QIcon(pixmap)


def _white_icon(widget: QWidget, sp: QStyle.StandardPixmap) -> QIcon:
    """Return a standard pixmap icon recolored to white."""
    pixmap = widget.style().standardIcon(sp).pixmap(24, 24)
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(255, 255, 255))
    painter.end()
    return QIcon(pixmap)


_STYLESHEET = f"""
MediaPlayerWidget {{
    background-color: {_BG};
    border: 1px solid {_OVERLAY};
    border-radius: 12px;
}}

QLabel {{
    color: {_TEXT};
    background: transparent;
}}

QSlider::groove:horizontal {{
    height: 6px;
    background: {_SURFACE};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {_ACCENT};
    width: 14px;
    height: 14px;
    margin: -4px 0;
    border-radius: 7px;
}}
QSlider::sub-page:horizontal {{
    background: {_ACCENT};
    border-radius: 3px;
}}

QSlider::groove:vertical {{
    width: 6px;
    background: {_SURFACE};
    border-radius: 3px;
}}
QSlider::handle:vertical {{
    background: {_BLUE};
    width: 10px;
    height: 10px;
    margin: 0 -2px;
    border-radius: 5px;
}}
QSlider::sub-page:vertical {{
    background: {_BLUE};
    border-radius: 3px;
}}

QPushButton {{
    background: transparent;
    color: {_TEXT};
    border: none;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 13px;
}}
QPushButton:hover {{
    background: {_SURFACE};
}}

QPushButton#play_pause {{
    background: {_ACCENT};
    color: {_BG};
    font-size: 16px;
    padding: 8px 16px;
    font-weight: bold;
}}
QPushButton#play_pause:hover {{
    background: {_BLUE};
}}

QPushButton#like_btn {{
    color: {_GREEN};
}}
QPushButton#dislike_btn {{
    color: {_RED};
}}

QComboBox {{
    background: {_SURFACE};
    color: {_TEXT};
    border: 1px solid {_OVERLAY};
    border-radius: 6px;
    padding: 4px 8px;
    min-width: 180px;
}}
QComboBox::drop-down {{
    border: none;
}}
QComboBox QAbstractItemView {{
    background: {_SURFACE};
    color: {_TEXT};
    selection-background-color: {_OVERLAY};
}}
"""

# Short labels for EQ frequencies
_EQ_LABELS = ["32", "64", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]


class MediaPlayerWidget(QWidget):
    """Dark-themed frameless popup media player widget."""

    sig_toggle_pause = Signal()
    sig_next = Signal()
    sig_prev = Signal()
    sig_seek_forward = Signal()
    sig_seek_backward = Signal()
    sig_seek_to = Signal(float)
    sig_set_volume = Signal(int)
    sig_rate_like = Signal()
    sig_rate_dislike = Signal()
    sig_search = Signal(str)
    sig_stop = Signal()
    sig_set_equalizer = Signal(list)
    sig_request_devices = Signal()
    sig_set_output_device = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setFixedWidth(380)
        self.setStyleSheet(_STYLESHEET)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._dragging_progress = False
        self._current_duration = 0.0
        self._devices: list[dict[str, str]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        # --- Track info ---
        info_row = QHBoxLayout()
        info_col = QVBoxLayout()
        self._title_label = QLabel("Not playing")
        self._title_label.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {_TEXT};")
        info_col.addWidget(self._title_label)
        self._artist_label = QLabel("")
        self._artist_label.setStyleSheet(f"font-size: 11px; color: {_DIM_TEXT};")
        info_col.addWidget(self._artist_label)
        info_row.addLayout(info_col, 1)
        self._pos_label = QLabel("")
        self._pos_label.setStyleSheet(f"font-size: 12px; color: {_ACCENT};")
        info_row.addWidget(self._pos_label)
        layout.addLayout(info_row)

        # --- Progress ---
        prog_row = QHBoxLayout()
        self._elapsed_label = QLabel("0:00")
        self._elapsed_label.setStyleSheet(f"font-size: 11px; color: {_DIM_TEXT};")
        self._elapsed_label.setFixedWidth(36)
        prog_row.addWidget(self._elapsed_label)
        self._progress_slider = QSlider(Qt.Orientation.Horizontal)
        self._progress_slider.setRange(0, 1000)
        self._progress_slider.setValue(0)
        self._progress_slider.sliderPressed.connect(self._on_progress_pressed)
        self._progress_slider.sliderReleased.connect(self._on_progress_released)
        prog_row.addWidget(self._progress_slider, 1)
        self._total_label = QLabel("0:00")
        self._total_label.setStyleSheet(f"font-size: 11px; color: {_DIM_TEXT};")
        self._total_label.setFixedWidth(36)
        self._total_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        prog_row.addWidget(self._total_label)
        layout.addLayout(prog_row)

        # --- Transport controls ---
        transport = QHBoxLayout()
        transport.addStretch()

        btn_prev = QPushButton()
        btn_prev.setIcon(_white_icon(self, QStyle.StandardPixmap.SP_MediaSkipBackward))
        btn_prev.clicked.connect(self.sig_prev)
        transport.addWidget(btn_prev)

        btn_seek_back = QPushButton()
        btn_seek_back.setIcon(_white_icon(self, QStyle.StandardPixmap.SP_MediaSeekBackward))
        btn_seek_back.clicked.connect(self.sig_seek_backward)
        transport.addWidget(btn_seek_back)

        self._btn_play_pause = QPushButton()
        self._btn_play_pause.setObjectName("play_pause")
        self._btn_play_pause.setIcon(_white_icon(self, QStyle.StandardPixmap.SP_MediaPlay))
        self._btn_play_pause.clicked.connect(self.sig_toggle_pause)
        transport.addWidget(self._btn_play_pause)

        btn_seek_fwd = QPushButton()
        btn_seek_fwd.setIcon(_white_icon(self, QStyle.StandardPixmap.SP_MediaSeekForward))
        btn_seek_fwd.clicked.connect(self.sig_seek_forward)
        transport.addWidget(btn_seek_fwd)

        btn_next = QPushButton()
        btn_next.setIcon(_white_icon(self, QStyle.StandardPixmap.SP_MediaSkipForward))
        btn_next.clicked.connect(self.sig_next)
        transport.addWidget(btn_next)

        transport.addStretch()
        layout.addLayout(transport)

        # --- Volume ---
        vol_row = QHBoxLayout()
        vol_icon = QLabel("\U0001f50a")
        vol_icon.setFixedWidth(24)
        vol_row.addWidget(vol_icon)
        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(100)
        self._volume_slider.valueChanged.connect(self._on_volume_changed)
        vol_row.addWidget(self._volume_slider, 1)
        self._volume_label = QLabel("100%")
        self._volume_label.setStyleSheet(f"font-size: 11px; color: {_DIM_TEXT};")
        self._volume_label.setFixedWidth(36)
        self._volume_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        vol_row.addWidget(self._volume_label)
        layout.addLayout(vol_row)

        # --- Equalizer ---
        eq_header = QHBoxLayout()
        eq_title = QLabel("Equalizer")
        eq_title.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {_TEXT};")
        eq_header.addWidget(eq_title)
        eq_header.addStretch()
        btn_reset_eq = QPushButton("Reset")
        btn_reset_eq.setFixedHeight(24)
        btn_reset_eq.clicked.connect(self._reset_equalizer)
        eq_header.addWidget(btn_reset_eq)
        layout.addLayout(eq_header)

        eq_sliders_row = QHBoxLayout()
        eq_sliders_row.setSpacing(4)
        self._eq_sliders: list[QSlider] = []
        for i, label_text in enumerate(_EQ_LABELS):
            col = QVBoxLayout()
            col.setSpacing(2)
            slider = QSlider(Qt.Orientation.Vertical)
            slider.setRange(-120, 120)
            slider.setValue(0)
            slider.setFixedHeight(100)
            slider.valueChanged.connect(self._on_eq_changed)
            col.addWidget(slider, 0, Qt.AlignmentFlag.AlignHCenter)
            lbl = QLabel(label_text)
            lbl.setStyleSheet(f"font-size: 9px; color: {_DIM_TEXT};")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(lbl)
            eq_sliders_row.addLayout(col)
            self._eq_sliders.append(slider)
        layout.addLayout(eq_sliders_row)

        # --- Output device ---
        dev_row = QHBoxLayout()
        dev_label = QLabel("Output:")
        dev_label.setStyleSheet(f"font-size: 12px; color: {_TEXT};")
        dev_row.addWidget(dev_label)
        self._device_combo = QComboBox()
        self._device_combo.currentIndexChanged.connect(self._on_device_changed)
        dev_row.addWidget(self._device_combo, 1)
        layout.addLayout(dev_row)

        # --- Actions ---
        actions = QHBoxLayout()
        btn_like = QPushButton("\u2665 Like")
        btn_like.setObjectName("like_btn")
        btn_like.clicked.connect(self.sig_rate_like)
        actions.addWidget(btn_like)
        btn_dislike = QPushButton("\U0001f44e Dislike")
        btn_dislike.setObjectName("dislike_btn")
        btn_dislike.clicked.connect(self.sig_rate_dislike)
        actions.addWidget(btn_dislike)
        btn_search = QPushButton("\U0001f50d Search")
        btn_search.clicked.connect(self._on_search)
        actions.addWidget(btn_search)
        btn_quit = QPushButton("Quit")
        btn_quit.clicked.connect(self._on_quit)
        actions.addWidget(btn_quit)
        layout.addLayout(actions)

    # --- Internal handlers ---
    def _on_progress_pressed(self) -> None:
        self._dragging_progress = True

    def _on_progress_released(self) -> None:
        self._dragging_progress = False
        if self._current_duration > 0:
            ratio = self._progress_slider.value() / 1000.0
            self.sig_seek_to.emit(ratio * self._current_duration)

    def _on_volume_changed(self, value: int) -> None:
        self._volume_label.setText(f"{value}%")
        self.sig_set_volume.emit(value)

    def _on_eq_changed(self) -> None:
        bands = [s.value() / 10.0 for s in self._eq_sliders]
        self.sig_set_equalizer.emit(bands)

    def _reset_equalizer(self) -> None:
        for s in self._eq_sliders:
            s.blockSignals(True)
            s.setValue(0)
            s.blockSignals(False)
        self.sig_set_equalizer.emit([0.0] * 10)

    def _on_device_changed(self, index: int) -> None:
        if 0 <= index < len(self._devices):
            self.sig_set_output_device.emit(self._devices[index]["name"])

    def _on_search(self) -> None:
        query, ok = QInputDialog.getText(self, "ytm-cli Search", "Search for:")
        if ok and query.strip():
            self.sig_search.emit(query.strip())

    def _on_quit(self) -> None:
        self.sig_stop.emit()
        QApplication.quit()

    # --- Public update slots ---
    @Slot(str, str, int, int)
    def on_track_changed(self, title: str, artist: str, pos: int, total: int) -> None:
        self._title_label.setText(title)
        self._artist_label.setText(artist)
        self._pos_label.setText(f"{pos}/{total}")

    @Slot(float, float, bool)
    def on_progress_updated(self, position: float, duration: float, paused: bool) -> None:
        self._current_duration = duration
        self._elapsed_label.setText(_format_time(position))
        self._total_label.setText(_format_time(duration))
        if not self._dragging_progress and duration > 0:
            self._progress_slider.setValue(int((position / duration) * 1000))
        sp = QStyle.StandardPixmap.SP_MediaPlay if paused else QStyle.StandardPixmap.SP_MediaPause
        self._btn_play_pause.setIcon(_white_icon(self, sp))

    @Slot()
    def on_playback_finished(self) -> None:
        self._title_label.setText("Queue finished")
        self._artist_label.setText("")
        self._pos_label.setText("")
        self._elapsed_label.setText("0:00")
        self._total_label.setText("0:00")
        self._progress_slider.setValue(0)

    @Slot(int)
    def on_volume_changed(self, volume: int) -> None:
        self._volume_slider.blockSignals(True)
        self._volume_slider.setValue(volume)
        self._volume_slider.blockSignals(False)
        self._volume_label.setText(f"{volume}%")

    @Slot(list)
    def on_devices_listed(self, devices: list) -> None:
        self._devices = devices
        self._device_combo.blockSignals(True)
        self._device_combo.clear()
        for dev in devices:
            label = dev["description"] if dev["name"] != "auto" else "Autoselect device"
            self._device_combo.addItem(label)
        self._device_combo.blockSignals(False)

    @Slot(str)
    def on_device_changed(self, name: str) -> None:
        for i, dev in enumerate(self._devices):
            if dev["name"] == name:
                self._device_combo.blockSignals(True)
                self._device_combo.setCurrentIndex(i)
                self._device_combo.blockSignals(False)
                break

    @Slot(str, bool)
    def on_rate_result(self, rating: str, success: bool) -> None:
        pass  # Notification handled by TrayIcon

    @Slot(str)
    def on_error(self, message: str) -> None:
        pass  # Notification handled by TrayIcon

    def show_near_tray(self, tray_geometry) -> None:
        """Position the popup near the system tray icon and show."""
        self.adjustSize()
        if tray_geometry and not tray_geometry.isNull():
            x = tray_geometry.x() + tray_geometry.width() // 2 - self.width() // 2
            y = tray_geometry.y() - self.height() - 8
            # Keep on screen
            screen = QApplication.primaryScreen()
            if screen:
                sr = screen.availableGeometry()
                x = max(sr.x(), min(x, sr.x() + sr.width() - self.width()))
                if y < sr.y():
                    y = tray_geometry.y() + tray_geometry.height() + 8
            self.move(x, y)
        else:
            # Fallback: bottom-right of screen
            screen = QApplication.primaryScreen()
            if screen:
                sr = screen.availableGeometry()
                x = sr.x() + sr.width() - self.width() - 16
                y = sr.y() + sr.height() - self.height() - 16
                self.move(x, y)
        self.show()


class PlaybackWorker(QObject):
    """Worker that manages Player and queue on a background QThread."""

    track_changed = Signal(str, str, int, int)
    progress_updated = Signal(float, float, bool)
    playback_finished = Signal()
    volume_changed = Signal(int)
    rate_result = Signal(str, bool)
    error_occurred = Signal(str)
    devices_listed = Signal(list)
    device_changed = Signal(str)

    def __init__(self, player: Player, api: YouTubeMusicAPI, queue: list, radio_mode: bool):
        super().__init__()
        self._player = player
        self._api = api
        self._queue: list[dict] = list(queue)
        self._queue_index: int = 0
        self._paused: bool = False
        self._radio_mode: bool = radio_mode
        self._poll_timer: QTimer | None = None
        self._stopped: bool = False
        self._current_label: str = ""

    @Slot()
    def setup(self) -> None:
        """Create the poll timer (must be called after moveToThread)."""
        self._poll_timer = QTimer()
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._poll_tick)

    @Slot()
    def start_playback(self) -> None:
        """Start playing the first track in the queue."""
        if not self._queue:
            self.playback_finished.emit()
            return
        self._queue_index = 0
        self._play_current()

    def _play_current(self) -> None:
        """Play the track at the current queue index."""
        if self._stopped or self._queue_index >= len(self._queue):
            self.playback_finished.emit()
            return

        track = self._queue[self._queue_index]
        video_id = track.get("videoId")
        if not video_id:
            self.error_occurred.emit("Invalid track (no videoId)")
            self._advance_queue()
            return

        try:
            self._player.play(video_id)
            self._paused = False
            title = track.get("title", "Unknown")
            artist = track.get("artist", "Unknown")
            self._current_label = f"{artist} - {title}"
            self.track_changed.emit(
                title,
                artist,
                self._queue_index + 1,
                len(self._queue),
            )
            if self._poll_timer:
                self._poll_timer.start()
        except Exception as e:
            self.error_occurred.emit(str(e))
            self._advance_queue()

    def _advance_queue(self) -> None:
        """Move to the next track, or fetch more in radio mode."""
        if self._stopped:
            return
        self._queue_index += 1
        if self._queue_index < len(self._queue):
            self._play_current()
        elif self._radio_mode:
            self._fetch_radio()
        else:
            self.playback_finished.emit()

    def _fetch_radio(self) -> None:
        """Fetch more radio tracks based on the last played track."""
        if not self._queue:
            self.playback_finished.emit()
            return

        last_track = self._queue[-1]
        video_id = last_track.get("videoId")
        if not video_id:
            self.playback_finished.emit()
            return

        existing_ids = {t.get("videoId") for t in self._queue}
        radio_tracks = self._api.get_radio(video_id, limit=50)
        new_tracks = [t for t in radio_tracks if t.get("videoId") not in existing_ids]

        if not new_tracks:
            self.playback_finished.emit()
            return

        self._queue.extend(new_tracks)
        self._play_current()

    @Slot()
    def _poll_tick(self) -> None:
        """Poll mpv for progress."""
        if self._stopped:
            return
        if self._player.is_active():
            position, duration = self._player.get_progress()
            self.progress_updated.emit(position, duration, self._paused)
            icon = "\u23f8" if self._paused else "\u25b6"
            if duration > 0:
                _write_now_playing(
                    f"{icon} {self._current_label}  "
                    f"{_format_time(position)}/{_format_time(duration)}"
                )
            else:
                _write_now_playing(f"{icon} {self._current_label}")
        else:
            if self._poll_timer:
                self._poll_timer.stop()
            self._advance_queue()

    @Slot()
    def toggle_pause(self) -> None:
        if self._paused:
            self._player.resume()
            self._paused = False
        else:
            self._player.pause()
            self._paused = True

    @Slot()
    def next_track(self) -> None:
        self._player.stop()
        if self._poll_timer:
            self._poll_timer.stop()
        self._advance_queue()

    @Slot()
    def prev_track(self) -> None:
        self._player.stop()
        if self._poll_timer:
            self._poll_timer.stop()
        self._queue_index = max(0, self._queue_index - 2)
        self._advance_queue()

    @Slot()
    def seek_forward(self) -> None:
        self._player.seek(10)

    @Slot()
    def seek_backward(self) -> None:
        self._player.seek(-10)

    @Slot(float)
    def seek_to(self, position: float) -> None:
        self._player.seek_absolute(position)

    @Slot(int)
    def set_volume(self, vol: int) -> None:
        self._player.set_volume(vol)
        self.volume_changed.emit(vol)

    @Slot(list)
    def set_equalizer(self, bands: list) -> None:
        self._player.set_equalizer(bands)

    @Slot()
    def request_devices(self) -> None:
        devices = self._player.get_audio_devices()
        self.devices_listed.emit(devices)

    @Slot(str)
    def set_output_device(self, name: str) -> None:
        self._player.set_audio_device(name)
        self.device_changed.emit(name)

    @Slot()
    def rate_like(self) -> None:
        if self._queue_index < len(self._queue):
            vid = self._queue[self._queue_index].get("videoId")
            if vid:
                success = self._api.rate_song(vid, "LIKE")
                self.rate_result.emit("LIKE", success)

    @Slot()
    def rate_dislike(self) -> None:
        if self._queue_index < len(self._queue):
            vid = self._queue[self._queue_index].get("videoId")
            if vid:
                success = self._api.rate_song(vid, "DISLIKE")
                self.rate_result.emit("DISLIKE", success)
                if success:
                    self._queue = [t for t in self._queue if t.get("videoId") != vid]
                    if self._queue_index >= len(self._queue):
                        self._queue_index = len(self._queue)
                    self._player.stop()
                    if self._poll_timer:
                        self._poll_timer.stop()
                    self._play_current()

    @Slot(str)
    def do_search(self, query: str) -> None:
        """Search for tracks and replace the queue."""
        self._player.stop()
        if self._poll_timer:
            self._poll_timer.stop()

        results = self._api.search(query, limit=20)
        if not results:
            self.error_occurred.emit(f"No results for '{query}'")
            return

        self._queue = results
        self._queue_index = 0
        self._radio_mode = False
        self._play_current()

    @Slot()
    def request_stop(self) -> None:
        """Stop playback and clean up."""
        self._stopped = True
        if self._poll_timer:
            self._poll_timer.stop()
        self._player.stop()
        _clear_now_playing()


class TrayIcon(QSystemTrayIcon):
    """System tray icon that owns the media player popup."""

    def __init__(self, parent=None):
        super().__init__(parent)

        icon = QIcon.fromTheme("audio-headphones")
        if icon.isNull():
            icon = _make_fallback_icon()
        self.setIcon(icon)
        self.setToolTip("ytm-cli")

        self._popup = MediaPlayerWidget()

        self.activated.connect(self._on_activated)

    @property
    def popup(self) -> MediaPlayerWidget:
        return self._popup

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.Context,
        ):
            if self._popup.isVisible():
                self._popup.hide()
            else:
                self._popup.show_near_tray(self.geometry())

    @Slot(str, str, int, int)
    def on_track_changed(self, title: str, artist: str, pos: int, total: int) -> None:
        self.setToolTip(f"{title} - {artist}")

    @Slot(str, bool)
    def on_rate_result(self, rating: str, success: bool) -> None:
        if success:
            label = "Liked!" if rating == "LIKE" else "Disliked"
            self.showMessage("ytm-cli", label, QSystemTrayIcon.MessageIcon.Information, 2000)

    @Slot(str)
    def on_error(self, message: str) -> None:
        self.showMessage("ytm-cli", f"Error: {message}", QSystemTrayIcon.MessageIcon.Warning, 3000)

    @Slot()
    def on_playback_finished(self) -> None:
        self.showMessage("ytm-cli", "Queue finished", QSystemTrayIcon.MessageIcon.Information, 3000)


def run_tray_mode(queue: list[dict], api: YouTubeMusicAPI, radio_mode: bool = False) -> None:
    """Launch the system tray UI and play the given queue."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("ytm-cli")

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("Error: System tray is not available on this system.")
        sys.exit(1)

    app.setQuitOnLastWindowClosed(False)

    player = Player()
    worker = PlaybackWorker(player, api, queue, radio_mode)
    thread = QThread()
    worker.moveToThread(thread)

    tray = TrayIcon()
    popup = tray.popup

    # Worker -> TrayIcon (notifications)
    worker.track_changed.connect(tray.on_track_changed)
    worker.playback_finished.connect(tray.on_playback_finished)
    worker.rate_result.connect(tray.on_rate_result)
    worker.error_occurred.connect(tray.on_error)

    # Worker -> Popup (UI updates)
    worker.track_changed.connect(popup.on_track_changed)
    worker.progress_updated.connect(popup.on_progress_updated)
    worker.playback_finished.connect(popup.on_playback_finished)
    worker.volume_changed.connect(popup.on_volume_changed)
    worker.rate_result.connect(popup.on_rate_result)
    worker.error_occurred.connect(popup.on_error)
    worker.devices_listed.connect(popup.on_devices_listed)
    worker.device_changed.connect(popup.on_device_changed)

    # Popup -> Worker (controls)
    popup.sig_toggle_pause.connect(worker.toggle_pause)
    popup.sig_next.connect(worker.next_track)
    popup.sig_prev.connect(worker.prev_track)
    popup.sig_seek_forward.connect(worker.seek_forward)
    popup.sig_seek_backward.connect(worker.seek_backward)
    popup.sig_seek_to.connect(worker.seek_to)
    popup.sig_set_volume.connect(worker.set_volume)
    popup.sig_rate_like.connect(worker.rate_like)
    popup.sig_rate_dislike.connect(worker.rate_dislike)
    popup.sig_search.connect(worker.do_search)
    popup.sig_stop.connect(worker.request_stop)
    popup.sig_set_equalizer.connect(worker.set_equalizer)
    popup.sig_request_devices.connect(worker.request_devices)
    popup.sig_set_output_device.connect(worker.set_output_device)

    # Thread lifecycle
    thread.started.connect(worker.setup)
    thread.started.connect(worker.start_playback)

    # Request device list after playback starts
    QTimer.singleShot(2000, worker.request_devices)

    thread.start()
    tray.show()
    app.exec()

    # Cleanup
    worker.request_stop()
    thread.quit()
    thread.wait()
    player.stop()
    _clear_now_playing()
