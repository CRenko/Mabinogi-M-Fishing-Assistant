"""安全进入背包整理：识别当前页面，不盲目重复切换 I 键。"""
from fishing_assistant.automation.models import EventKind
from fishing_assistant.inventory_cleanup import InventoryCleanupVision, SimpleCleanupState


class InventoryEntryMixin:
    def _detect_cleanup_entry(self, frame):
        simple = InventoryCleanupVision.inspect_simple_screen(frame)
        return simple if simple is not None else InventoryCleanupVision.find_inventory_tidy(frame)

    def _open_cleanup_panel(self, screen, config, generation):
        self._ensure_cleanup_active(generation)
        frame = self._capture_stamina_frame(screen, config)[:, :, :3]
        state = self._detect_cleanup_entry(frame)
        self._ensure_cleanup_active(generation)
        if state is None:
            inventory_open = InventoryCleanupVision.find_inventory_tab(frame) is not None
            self._ensure_cleanup_active(generation)
            if not inventory_open:
                self._press_key("i", config)
            else:
                self._emit(EventKind.INFO, "OK 已确认背包打开，等待整理入口显示，不重复按 I。", monitoring=True)
            _frame, state = self._wait_cleanup_screen(screen, config, generation,
                self._detect_cleanup_entry, "背包入口或简单整理页面")
        if isinstance(state, SimpleCleanupState):
            self._emit(EventKind.INFO, "OK 已确认简单整理页面，无需再次按 I 或点击整理入口。", monitoring=True)
            return state
        self._emit(EventKind.INFO, f"OK 已确认背包整理入口，相似度 {state.confidence:.3f}；正在打开简单整理。", monitoring=True)
        self._ensure_cleanup_active(generation)
        self._click_game_point(state.center, config, screen)
        _frame, simple = self._wait_cleanup_screen(screen, config, generation,
            InventoryCleanupVision.inspect_simple_screen, "简单整理页面")
        return simple
