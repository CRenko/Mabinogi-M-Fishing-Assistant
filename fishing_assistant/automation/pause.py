"""悬浮栏任务暂停/继续；暂停不释放任务占用，停止仍会取消任务。"""
import time

from fishing_assistant.automation.models import EventKind


class PauseControlMixin:
    def is_paused(self) -> bool:
        return self._paused.is_set() and self._enabled.is_set()

    def pause_task(self) -> bool:
        if not self._enabled.is_set() or self._shutdown.is_set():
            return False
        if self._cleanup_in_progress.is_set() or self._cleanup_test_requested.is_set():
            self.set_monitoring(False)
            self._emit(EventKind.WARNING, "背包整理已安全停止，请检查游戏页面；不会自动继续整理确认。", monitoring=False)
            return True
        if self._paused.is_set():
            return True
        self._paused_at = time.monotonic()
        self._paused.set()
        self._interrupt_generation += 1
        self._emit(EventKind.PAUSE, "任务已暂停，点击悬浮栏“继续”可恢复；游戏本身不会暂停。", monitoring=True)
        return True

    def resume_task(self) -> bool:
        with self._config_lock:
            if not self.is_paused() or self._shutdown.is_set():
                return False
            now = time.monotonic()
            if self._craft_request is not None:
                with self._craft_session_lock:
                    if self._craft_request is None or not self.is_paused():
                        return False
                    session, _target = self._craft_request
                    session.resume_after_pause(max(0.0, now - self._paused_at))
            else:
                # 鱼可能在暂停期间逃走：重新看画面，不沿用暂停前的收杆判断。
                self._reset_detection()
                self._startup_probe_active = True
                self._schedule_recast(now, self.config(), "悬浮栏继续")
            self._interrupt_generation += 1
            self._paused.clear()
            self._emit(EventKind.PAUSE, "任务已继续，正在重新核对游戏画面。", monitoring=True)
            return True
