"""在钓鱼引擎的同一任务线程内执行加工；复用 OK WGC / PostMessage。"""
from __future__ import annotations
import time
from fishing_assistant import window_target
from fishing_assistant.automation.models import EventKind, _OperationCancelled
from fishing_assistant.features.crafting.model import CraftSession
from fishing_assistant.features.crafting.recognition import CraftVision


def _step_and_send(engine, session, view, snapshot, target, original):
    """暂停取消尚未发送的决定；已发送的动作保留等待确认，避免重复添加。"""
    with engine._craft_session_lock:
        checkpoint = session.__dict__.copy()
        input_started = False

        def before_input():
            nonlocal input_started
            engine._ensure_operation_active()
            input_started = True

        try:
            engine._ensure_operation_active()
            decision = session.step(view, time.monotonic())
            if decision.action == "wait":
                return decision
            latest = window_target.get_window_info(original.handle)
            if latest is None or (latest.title, latest.width, latest.height) != (target.title, target.width, target.height):
                raise RuntimeError("操作前窗口发生改变，已停止，未发送按键。")
            with engine._backend_lock:
                engine._ensure_operation_active()
                backend = engine._get_ok_window_backend(latest)
                engine._ensure_operation_active()
                if decision.action in {"open_recipe", "collect"}:
                    backend.click_client(latest, snapshot, decision.point, before_input=before_input,
                                         check_active=engine._ensure_operation_active)
                else:
                    backend.hover_client(latest, snapshot, decision.point,
                                         before_input=engine._ensure_operation_active)
                    engine._ensure_operation_active()
                    backend.tap_client_key(latest, snapshot,
                        "esc" if decision.action == "close_dialog" else "space", before_input=before_input,
                        check_active=engine._ensure_operation_active)
            return decision
        except _OperationCancelled:
            if not input_started and engine.is_paused() and not session.finished:
                session.__dict__.update(checkpoint)
            raise


def run_crafting(engine, request, generation: int) -> None:
    session, original = request
    vision = CraftVision()
    failures = 0
    last_note = ""
    last_emit = 0.0
    last_log = 0.0
    last_geometry = None
    try:
        while engine._operation_active(generation) and not session.finished:
            try:
                # 只使用启动时确认的句柄，不根据标题自动重定向到别的窗口。
                target = window_target.get_window_info(original.handle)
                if target is None or target.title != original.title:
                    raise RuntimeError("目标游戏窗口已关闭或改变，请重新选择。")
                with engine._backend_lock:
                    engine._ensure_operation_active()
                    backend = engine._get_ok_window_backend(target)
                    snapshot = backend.capture_client_frame(target)
                if snapshot.description != last_geometry:
                    engine._emit(EventKind.INFO, f"WGC 捕获客户区：{snapshot.description}")
                    last_geometry = snapshot.description
                view = vision.inspect(snapshot.image, session.options.recipe, queue_capacity=session.queue_capacity)
                engine._ensure_operation_active()
                decision = _step_and_send(engine, session, view, snapshot, target, original)
                now = time.monotonic()
                if decision.message or session.message != last_note or now-last_emit >= 2:
                    engine._emit_crafting(session.progress(now, generation),
                        log=bool(decision.message) or now-last_log >= 30)
                    if decision.message or now-last_log >= 30:
                        last_log = now
                    last_note, last_emit = session.message, now
                failures = 0
            except Exception as error:
                if not engine._operation_active(generation):
                    return
                # 动作发出前后均可能发生异常。只重试截图阶段；已经决定操作则停止。
                if session.phase in {"await_dialog", "await_add", "await_result", "await_return", "await_close"}:
                    session.stop(f"加工操作未确认：{error}；请检查队列后重新开始。", error=True)
                else:
                    failures += 1
                    if failures > 3:
                        session.stop(f"连续 4 次获取加工画面失败，已停止：{error}", error=True)
                    else:
                        session.message = f"加工画面暂不可用，正在重试 {failures}/3：{error}"
                        engine._emit_crafting(session.progress(time.monotonic(), generation), log=True)
                if not session.finished:
                    engine._shutdown.wait(0.5)
            engine._shutdown.wait(0.35 if session.phase != "inspect" else 0.7)
        if session.finished and engine._operation_active(generation):
            engine._enabled.clear()
            engine._emit_crafting(session.progress(time.monotonic(), generation), log=True)
    finally:
        if engine._craft_request is request and generation == engine._interrupt_generation:
            engine._craft_request = None
