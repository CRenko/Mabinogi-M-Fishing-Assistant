"""OK 客户区截图的坐标契约；不改变旧 F7 窗口外框坐标。"""
from __future__ import annotations

import ctypes
import math
import sys
from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np


@contextmanager
def physical_window_coordinates():
    """只在后台当前线程使用物理像素，不修改 Qt/整个进程的 DPI 策略。"""
    if sys.platform != "win32":
        raise RuntimeError("OK 客户区截图仅支持 Windows。")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    setter = user32.SetThreadDpiAwarenessContext
    setter.argtypes = [ctypes.c_void_p]
    setter.restype = ctypes.c_void_p
    previous = setter(ctypes.c_void_p(-4))  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    if not previous:
        raise RuntimeError("无法建立后台 DPI 坐标上下文，未发送操作。")
    try:
        yield
    finally:
        setter(previous)


@dataclass(frozen=True, slots=True)
class ClientGeometry:
    handle: int
    title: str
    left: int
    top: int
    width: int
    height: int
    window_width: int
    window_height: int
    dpi_scale: float

    @property
    def layout_signature(self) -> tuple:
        # 同 DPI 下移动窗口不改变客户区内点击坐标；跨屏缩放需要新截图。
        return (self.handle, self.title, self.width, self.height,
                self.window_width, self.window_height, self.dpi_scale)


def read_client_geometry(handle: int, title: str) -> ClientGeometry:
    """复用 OK 自身的窗口测量；调用者须处于 physical_window_coordinates 中。"""
    import win32gui
    from ok.util.window import get_window_bounds

    if (not win32gui.IsWindow(handle) or not win32gui.IsWindowVisible(handle)
            or win32gui.IsIconic(handle) or win32gui.GetWindowText(handle) != title):
        raise RuntimeError("目标窗口已关闭、最小化或改变，未发送操作。")
    left, top, ww, wh, width, height, dpi = get_window_bounds(handle)
    if min(width, height, ww, wh) <= 0 or not math.isfinite(dpi) or dpi <= 0:
        raise RuntimeError("OK 未能取得有效的游戏客户区，请恢复目标窗口。")
    return ClientGeometry(handle, title, left, top, width, height, ww, wh, dpi)


@dataclass(frozen=True, slots=True)
class ClientFrame:
    image: np.ndarray
    geometry: ClientGeometry

    def validate(self) -> None:
        if self.image.ndim != 3 or not self.image.size or min(self.geometry.width, self.geometry.height) <= 0:
            raise RuntimeError("OK 返回了无效客户区画面。")
        height, width = self.image.shape[:2]
        # OK WGC 已按客户区裁掉标题栏/边框。这里不比较窗口外框，也不设分辨率名单。
        # 一像素误差仅来自 OK 边框居中取整，不接受旧帧/任意裁切图的盲目拉伸。
        if abs(width-self.geometry.width) > 1 or abs(height-self.geometry.height) > 1:
            raise RuntimeError(f"OK 客户区画面尚未同步（{self.description}），未发送操作。")

    @property
    def description(self) -> str:
        height, width = self.image.shape[:2]
        g = self.geometry
        return (f"截图 {width}×{height} / 客户区 {g.width}×{g.height} / "
                f"窗口 {g.window_width}×{g.window_height} / DPI {g.dpi_scale:.0%}")

    def client_point(self, point: tuple[int, int] | None) -> tuple[int, int]:
        self.validate()
        height, width = self.image.shape[:2]
        if point is None:
            point = (width // 2, height // 2)
        x, y = point
        if not (math.isfinite(x) and math.isfinite(y) and 0 <= x < width and 0 <= y < height):
            raise RuntimeError("识别位置超出当前客户区画面，未发送操作。")
        # 识别器已把归一化工作图坐标还原成此帧坐标；绝不能再乘 Windows DPI。
        return (min(self.geometry.width-1, round(x*self.geometry.width/width)),
                min(self.geometry.height-1, round(y*self.geometry.height/height)))

    def ensure_current(self, current: ClientGeometry) -> None:
        if current.layout_signature != self.geometry.layout_signature:
            raise RuntimeError("操作前客户区尺寸或 DPI 已改变，未发送操作；请重新开始制作。")
