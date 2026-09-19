"""前台／后台截图、坐标换算及 OK 后台实例管理"""
from __future__ import annotations

import mss
import numpy as np
from dataclasses import replace
from fishing_assistant import window_target
from fishing_assistant.automation.models import (
    EventKind,
    IconColorSignals,
    IconState,
    StaminaBarSample,
    _OperationCancelled,
)
from fishing_assistant.config import APP_DIR, AppConfig, effective_roi_size
from fishing_assistant.vision.shadow import ShadowRecorder


class CaptureMixin:
    """前台／后台截图、坐标换算及 OK 后台实例管理；由 FishingEngine 组装，不单独实例化。"""

    def _capture_frame(self, screen: mss.MSS | None, config: AppConfig) -> np.ndarray:
        self._ensure_operation_active()
        if config.capture_mode == "window":
            if config.target_button_offset is None:
                raise RuntimeError("目标窗口尚未完成按钮校准。")
            target = self._resolve_target_window(config)
            self._maintain_background_hover(target, config)
            roi_width, roi_height = effective_roi_size(
                config, (target.width, target.height)
            )
            if config.window_backend == "ok":
                # 持锁跨越「取得＋使用」：避免另一线程在取得与截图之间
                # 关闭同一个 WGC 会话（borrow/use/close 竞态）。
                with self._backend_lock:
                    return self._get_ok_window_backend(target).capture_region(
                        target,
                        config.target_button_offset,
                        roi_width,
                        roi_height,
                    )
            return window_target.capture_window_region(
                target.handle,
                config.target_button_offset,
                roi_width,
                roi_height,
            )
        if screen is None:
            raise RuntimeError("屏幕截图服务未初始化。")
        return np.asarray(screen.grab(self._capture_region(config)))

    def _shadow_observe(
        self,
        roi_bgr: np.ndarray,
        icon_state: IconState,
        signals: IconColorSignals,
        screen: mss.MSS | None,
        config: AppConfig,
    ) -> None:
        """影子模式旁路：v2 链并行判定 + 上钩瞬间全帧采集，绝不抛异常。"""
        try:
            if self._shadow_recorder is None:
                self._shadow_recorder = ShadowRecorder(APP_DIR / "v2_shadow")
            self._shadow_recorder.record_icon(
                roi_bgr, icon_state.value, signals.recognition_confidence
            )
            if (
                icon_state == IconState.FISH_HOOKED
                and self._shadow_prev_icon != IconState.FISH_HOOKED
            ):
                full = self._capture_stamina_frame(screen, config)
                self._shadow_recorder.record_hook_transition(full[:, :, :3])
            self._shadow_prev_icon = icon_state
        except Exception:
            pass

    def _capture_stamina_frame(
        self, screen: mss.MSS | None, config: AppConfig
    ) -> np.ndarray:
        """取得完整游戏画面，供动态体力条和全局提示扫描复用。"""
        if config.capture_mode == "window":
            target = self._resolve_target_window(config)
            self._maintain_background_hover(target, config)
            if config.window_backend == "ok":
                with self._backend_lock:
                    return self._get_ok_window_backend(target).capture_frame(
                        target
                    )
            return window_target.capture_window_frame(target.handle)
        if screen is None:
            raise RuntimeError("屏幕截图服务未初始化。")
        monitor_index = min(max(1, config.monitor_index), len(screen.monitors) - 1)
        return np.asarray(screen.grab(screen.monitors[monitor_index]))

    def _capture_stamina_sample(
        self, screen: mss.MSS | None, config: AppConfig, now: float
    ) -> StaminaBarSample | None:
        # 反弹窗口较短；上钩期间每次主循环都允许完整画面采样，旧配置的 100 ms
        # 不再把真实反弹漏在两次扫描之间。
        interval = max(40, min(75, config.stamina_scan_interval_ms)) / 1000
        if now - self._last_stamina_scan_at < interval:
            return None
        self._last_stamina_scan_at = now
        try:
            frame = self._capture_stamina_frame(screen, config)
            self._ensure_operation_active()
        except _OperationCancelled:
            raise
        except Exception as error:  # pragma: no cover - 由实际窗口捕捉环境决定
            self._ensure_operation_active()
            if now - self._last_stamina_warning_at >= 3.0:
                self._emit(EventKind.WARNING, f"无法读取活鱼体力条：{error}")
                self._last_stamina_warning_at = now
            return None
        game_frame = frame[:, :, :3]
        if config.v2_vision_enabled:
            # v2 路径：降采样粗扫+干净锚点模板，内建就近偏好，
            # 不需要旧路径的 nearby 降级重试。
            sample = self._find_stamina_bar_v2_sample(game_frame)
        else:
            sample = self.find_stamina_bar(game_frame, require_anchor=True)
        if (
            sample is None
            and not config.v2_vision_enabled
            and self._stamina_bar_seen
            and self._stamina_last_center is not None
        ):
            # OK 锚点偶发动画漏帧时，只接受紧邻上一位置的槽体候选；
            # 不会退回全画面任意绿色像素，也不会改变用户选择的图标识别模式。
            nearby = self.find_stamina_bar(
                game_frame,
                require_anchor=False,
                preferred_center=self._stamina_last_center,
            )
            if nearby is not None:
                distance = float(
                    np.hypot(
                        nearby.center[0] - self._stamina_last_center[0],
                        nearby.center[1] - self._stamina_last_center[1],
                    )
                )
                movement_limit = max(
                    80.0, min(game_frame.shape[0], game_frame.shape[1]) * 0.18
                )
                if distance <= movement_limit:
                    sample = replace(nearby, anchor_confidence=0.0)
        if sample is None:
            if now - self._last_stamina_missing_log_at >= 2.0:
                source = (
                    "目标窗口完整画面"
                    if config.capture_mode == "window"
                    else "当前显示器完整画面"
                )
                self._emit(
                    EventKind.INFO,
                    f"体力条扫描：在{source}中暂未同时确认中鱼图标与"
                    "角色头顶绿条，将继续扫描。",
                    monitoring=True,
                )
                self._last_stamina_missing_log_at = now
            return None
        probe_offset = self._stamina_probe_offset_x
        if probe_offset is None:
            probe_offset = max(1, sample.fill_width // 2)
        return self.classify_stamina_midpoint(game_frame, sample, probe_offset)

    def _capture_escape_message_confidence(
        self, screen: mss.MSS | None, config: AppConfig, now: float
    ) -> float:
        if now - self._last_escape_scan_at < 0.14:
            return 0.0
        self._last_escape_scan_at = now
        try:
            frame = self._capture_stamina_frame(screen, config)
            self._ensure_operation_active()
        except _OperationCancelled:
            raise
        except Exception as error:  # pragma: no cover - 由实际窗口捕捉环境决定
            self._ensure_operation_active()
            if now - self._last_stamina_warning_at >= 3.0:
                self._emit(EventKind.WARNING, f"无法扫描跑鱼提示：{error}")
                self._last_stamina_warning_at = now
            return 0.0
        confidence = self.fish_escape_message_confidence(frame[:, :, :3])
        if confidence >= self.ESCAPE_MESSAGE_MATCH_THRESHOLD:
            self._emit(
                EventKind.INFO,
                f"跑鱼文字模板命中：相似度 {confidence:.3f}。",
                monitoring=True,
            )
        return confidence

    def _capture_blocking_message_confidences(
        self, screen: mss.MSS | None, config: AppConfig, now: float
    ) -> tuple[float, float] | None:
        if (
            now - self._last_blocking_message_scan_at
            < self.BLOCKING_MESSAGE_SCAN_INTERVAL_SECONDS
        ):
            return None
        self._last_blocking_message_scan_at = now
        try:
            frame = self._capture_stamina_frame(screen, config)
            self._ensure_operation_active()
        except _OperationCancelled:
            raise
        except Exception as error:  # pragma: no cover - 由实际窗口捕捉环境决定
            self._ensure_operation_active()
            if now - self._last_blocking_message_warning_at >= 3.0:
                self._emit(EventKind.WARNING, f"无法扫描钓鱼阻塞提示：{error}")
                self._last_blocking_message_warning_at = now
            return None

        bgr = frame[:, :, :3]
        rod_confidence = self.rod_required_message_confidence(bgr)
        inventory_text_confidence = self.inventory_full_message_confidence(bgr)
        inventory_icon_confidence = self.inventory_full_icon_confidence(bgr)
        inventory_confidence = inventory_text_confidence
        if inventory_icon_confidence >= self.INVENTORY_FULL_ICON_MATCH_THRESHOLD:
            inventory_confidence = max(
                inventory_confidence, inventory_icon_confidence
            )
        if rod_confidence >= self.ROD_REQUIRED_MATCH_THRESHOLD:
            self._emit(
                EventKind.INFO,
                f"鱼竿状态文字由 OK 特征识别命中：相似度 {rod_confidence:.3f}。",
                monitoring=True,
            )
        if inventory_text_confidence >= self.INVENTORY_FULL_MATCH_THRESHOLD:
            self._emit(
                EventKind.INFO,
                "背包已满文字由 OK 特征识别命中："
                f"相似度 {inventory_text_confidence:.3f}。",
                monitoring=True,
            )
        if inventory_icon_confidence >= self.INVENTORY_FULL_ICON_MATCH_THRESHOLD:
            self._emit(
                EventKind.INFO,
                "红色背包图标由 OK 彩色特征识别命中："
                f"相似度 {inventory_icon_confidence:.3f}。",
                monitoring=True,
            )
        return rod_confidence, inventory_confidence

    def _resolve_target_window(self, config: AppConfig) -> window_target.WindowInfo:
        target = window_target.resolve_window(
            config.target_window_handle, config.target_window_title
        )
        if target is None:
            raise RuntimeError("找不到已选窗口；请刷新列表并重新选择。")
        if target.handle != config.target_window_handle:
            self.update_config(
                target_window_handle=target.handle,
                target_window_title=target.title,
            )
        return target

    def _get_ok_window_backend(
        self, target: window_target.WindowInfo
    ) -> window_target.OkWindowBackend:
        # 监测线程与快捷键线程（F9 快照）可能同时到达；不加锁会建出
        # 两个 WGC 会话，其中一个失去引用后不会被关闭。
        with self._backend_lock:
            if self._ok_window_backend is None or self._ok_window_backend.handle != target.handle:
                self._close_ok_window_backend()
                self._ok_window_backend = window_target.OkWindowBackend(target)
            self._ok_window_backend.update(target)
            return self._ok_window_backend

    def _close_ok_window_backend(self) -> None:
        with self._backend_lock:
            if self._ok_window_backend is not None:
                self._ok_window_backend.close()
                self._ok_window_backend = None

    @staticmethod
    def _capture_region(config: AppConfig) -> dict[str, int]:
        if config.button_center is None:
            raise RuntimeError("未设置钓鱼按钮中心")
        x, y = config.button_center
        roi_width, roi_height = effective_roi_size(config)
        return {
            "left": int(x - roi_width // 2),
            "top": int(y - roi_height // 2),
            "width": int(roi_width),
            "height": int(roi_height),
        }
