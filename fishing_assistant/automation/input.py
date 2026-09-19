"""集中发送游戏鼠标／键盘操作，并检查任务停止资格"""
from __future__ import annotations

import mss
import pyautogui
import time
from fishing_assistant import window_target
from fishing_assistant.automation.models import EventKind
from fishing_assistant.config import AppConfig, effective_roi_size


class GameInputMixin:
    """集中发送游戏鼠标／键盘操作，并检查任务停止资格；由 FishingEngine 组装，不单独实例化。"""

    def _click_game_point(
        self,
        point: tuple[int, int],
        config: AppConfig,
        screen: mss.MSS | None,
    ) -> None:
        self._ensure_operation_active()
        if config.capture_mode == "window":
            target = self._resolve_target_window(config)
            if config.window_backend == "ok":
                with self._backend_lock:
                    backend = self._get_ok_window_backend(target)
                    self._ensure_operation_active()
                    backend.click(target, point)
            else:
                self._ensure_operation_active()
                window_target.post_mouse_click(target.handle, point)
            return
        if screen is None:
            raise RuntimeError("屏幕点击服务未初始化")
        monitor_index = min(
            max(1, int(config.monitor_index)), len(screen.monitors) - 1
        )
        monitor = screen.monitors[monitor_index]
        self._ensure_operation_active()
        pyautogui.click(
            int(monitor["left"]) + int(point[0]),
            int(monitor["top"]) + int(point[1]),
        )

    def _restore_fishing_pointer(self, config: AppConfig) -> None:
        self._ensure_operation_active()
        if config.capture_mode == "window":
            target = self._resolve_target_window(config)
            self._maintain_background_hover(target, config, force=True)
        elif config.button_center is not None:
            pyautogui.moveTo(*config.button_center)

    def _maintain_background_hover(
        self,
        target: window_target.WindowInfo,
        config: AppConfig,
        *,
        force: bool = False,
    ) -> None:
        """让目标窗口持续认为鼠标停在校准点，不改变系统真实光标。"""
        self._ensure_operation_active()
        offset = config.target_button_offset
        if offset is None:
            return
        now = time.monotonic()
        if not force and now - self._last_background_hover_at < 0.40:
            return
        if config.window_backend == "ok":
            with self._backend_lock:
                self._get_ok_window_backend(target).keep_hover(target, offset)
        else:
            window_target.post_mouse_move(target.handle, offset)
        self._last_background_hover_at = now

    def _refresh_background_hover(self, config: AppConfig) -> None:
        """向空白处再回到按钮，触发游戏重新计算首次交互悬停。"""
        if config.capture_mode != "window":
            return
        offset = config.target_button_offset
        if offset is None:
            return
        target = self._resolve_target_window(config)
        roi_width, roi_height = effective_roi_size(
            config, (target.width, target.height)
        )
        neutral = (target.width // 2, target.height // 2)
        separation = max(120, roi_width, roi_height)
        if (
            abs(neutral[0] - offset[0]) < separation
            and abs(neutral[1] - offset[1]) < separation
        ):
            candidate_x = offset[0] - separation * 2
            if candidate_x < 0:
                candidate_x = offset[0] + separation * 2
            neutral = (
                min(max(0, candidate_x), max(0, target.width - 1)),
                min(max(0, offset[1]), max(0, target.height - 1)),
            )

        if config.window_backend == "ok":
            with self._backend_lock:
                backend = self._get_ok_window_backend(target)
                backend.keep_hover(target, neutral)
                time.sleep(self.BACKGROUND_HOVER_REFRESH_DELAY_SECONDS)
                backend.keep_hover(target, offset)
        else:
            window_target.post_mouse_move(target.handle, neutral)
            time.sleep(self.BACKGROUND_HOVER_REFRESH_DELAY_SECONDS)
            window_target.post_mouse_move(target.handle, offset)
        time.sleep(self.BACKGROUND_HOVER_REFRESH_DELAY_SECONDS)
        self._last_background_hover_at = time.monotonic()
        self._emit(
            EventKind.INFO,
            "移动恢复后已刷新后台虚拟悬停，准备发送 Space。",
            monitoring=True,
        )

    def _press_key(self, key: str, config: AppConfig) -> None:
        self._ensure_operation_active()
        if config.capture_mode == "window":
            target = self._resolve_target_window(config)
            self._maintain_background_hover(target, config, force=True)
            if config.window_backend == "ok":
                with self._backend_lock:
                    backend = self._get_ok_window_backend(target)
                    self._ensure_operation_active()
                    backend.tap_key(key)
            else:
                self._ensure_operation_active()
                window_target.post_key_tap(target.handle, key, activate_message=True)
            return
        if key.lower() == "esc":
            # 屏幕模式必须发送真实 Esc；短暂忽略由此产生的全局监听回调，
            # 避免把助手自己退出背包的按键当成用户紧急停止。
            self._ignore_esc_until = time.monotonic() + 0.8
        pyautogui.press(key)

    def _tap_key(self, key: str, hold_ms: int, config: AppConfig) -> None:
        self._ensure_operation_active()
        if config.capture_mode == "window":
            target = self._resolve_target_window(config)
            self._maintain_background_hover(target, config, force=True)
            if config.window_backend == "ok":
                with self._backend_lock:
                    backend = self._get_ok_window_backend(target)
                    self._ensure_operation_active()
                    backend.tap_key(key, hold_ms)
            else:
                self._ensure_operation_active()
                window_target.post_key_tap(
                    target.handle, key, hold_ms, activate_message=True
                )
            return
        pyautogui.keyDown(key)
        try:
            time.sleep(hold_ms / 1000)
        finally:
            pyautogui.keyUp(key)
