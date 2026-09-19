"""OK 客户区输入保护：不移动真实鼠标，逐条检查任务，投递失败向上报告。"""
from contextlib import contextmanager

import win32con
import win32gui
from ok.device.interaction_methods.post_message import PostMessageInteraction


class CheckedPostMessageInteraction(PostMessageInteraction):
    """沿用 OK 的坐标转换与输入序列；仅显式客户区操作启用严格检查。"""

    _client_guard = None
    _DOWN = {win32con.WM_LBUTTONDOWN, win32con.WM_RBUTTONDOWN,
             win32con.WM_MBUTTONDOWN, win32con.WM_KEYDOWN}
    _UP = {win32con.WM_LBUTTONUP, win32con.WM_RBUTTONUP,
           win32con.WM_MBUTTONUP, win32con.WM_KEYUP}

    @contextmanager
    def input_guard(self, check_active, before_input):
        if self._client_guard is not None:
            raise RuntimeError("不能并行发送后台客户区操作。")
        self._client_guard = (check_active, before_input)
        try:
            check_active()
            yield
        finally:
            self._client_guard = None

    def post(self, message, wParam=0, lParam=0, hwnd=None):
        if self._client_guard is None:
            return super().post(message, wParam, lParam, hwnd)
        check_active, before_input = self._client_guard
        # 停止后仍须释放已经按下的按键，但不再激活、悬停或按下新按键。
        if message not in self._UP:
            check_active()
        if message in self._DOWN:
            before_input()
        target = self.hwnd if hwnd is None else hwnd
        try:
            # OK 默认 post 会吞掉异常。严格通路保留原消息，失败时终止任务。
            win32gui.PostMessage(target, message, wParam, lParam)
        except Exception as error:
            raise RuntimeError(f"PostMessage 输入消息发送失败（窗口 {target}，消息 {message:#x}）：{error}") from error
