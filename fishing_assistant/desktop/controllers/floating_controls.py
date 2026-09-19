"""悬浮栏按钮只调用引擎任务入口，不直接发送游戏按键。"""


class FloatingControlsMixin:
    def _pause_from_floating(self):
        self.engine.pause_task()
        self._sync_floating_task_controls()

    def _resume_from_floating(self):
        self.engine.resume_task()
        self._sync_floating_task_controls()

    def _sync_floating_task_controls(self):
        self.floating_status_bar.set_task_controls(
            self.engine.is_monitoring(), self.engine.is_paused() is True
        )
