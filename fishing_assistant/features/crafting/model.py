"""自动加工的配方目录和纯状态机；不直接截图、不发送按键。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Recipe:
    key: str
    category: str
    name: str
    seconds: int


CATEGORIES = {"wood": "木材加工", "metal": "金属加工", "cloth": "布料加工", "leather": "皮革加工"}
RECIPES = (
    Recipe("wood", "wood", "木材", 90),
    Recipe("wood_plus", "wood", "木材+", 720),
    Recipe("iron_ore", "metal", "铁锭（矿石）", 60),
    Recipe("iron_iron_ore", "metal", "铁锭（铁矿石）", 60),
    Recipe("steel", "metal", "钢锭", 600),
    Recipe("cloth", "cloth", "布料", 90),
    Recipe("silk", "cloth", "丝绸", 180),
    Recipe("cloth_plus", "cloth", "布料+", 720),
    Recipe("leather", "leather", "皮革", 60),
    Recipe("leather_plus", "leather", "皮革+", 600),
)
RECIPE_BY_KEY = {recipe.key: recipe for recipe in RECIPES}
MAX_QUEUE_CAPACITY = 32  # 可见队列的安全扫描上限，不代表游戏已经开放这么多格。


def duration(seconds: float) -> str:
    seconds = max(0, round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return (f"{hours}小时" if hours else "") + (f"{minutes}分" if minutes else "") + (f"{seconds}秒" if seconds or not (hours or minutes) else "")


@dataclass(frozen=True)
class CraftOptions:
    recipe: str = "wood"
    mode: str = "count"
    count: int = 4
    queue_capacity: int = 0  # 0 为自动；与本次加工次数是两个不同概念。

    def validate(self) -> None:
        if self.recipe not in RECIPE_BY_KEY or self.mode not in {"count", "exhaust"}:
            raise ValueError("请选择有效的材料和制作模式。")
        if type(self.count) is not int or not 1 <= self.count <= 10000:
            raise ValueError("加工次数须为 1～10000。")
        if type(self.queue_capacity) is not int or not 0 <= self.queue_capacity <= MAX_QUEUE_CAPACITY:
            raise ValueError(f"队列容量须为自动或 1～{MAX_QUEUE_CAPACITY} 格。")


@dataclass(frozen=True)
class CraftView:
    category: str = ""
    # unknown 绝不当作空槽；complete 只由 100% 文字确认。
    slots: tuple[str, ...] = ()
    recipe_point: tuple[int, int] | None = None
    collect_point: tuple[int, int] | None = None
    dialog_recipe: str = ""
    dialog_open: bool = False
    process_point: tuple[int, int] | None = None
    result: bool = False
    insufficient: bool = False
    detail: str = ""
    queue_complete: bool = True  # False 表示边缘截断或未能确认完整队列布局。


@dataclass(frozen=True)
class CraftDecision:
    action: str = "wait"
    point: tuple[int, int] | None = None
    message: str = ""


@dataclass(frozen=True)
class CraftProgress:
    phase: str
    message: str
    submitted: int
    collected: int
    slots: tuple[str, ...]
    estimate_seconds: float
    running: bool
    generation: int = 0


class CraftSession:
    """每次动作都等待画面确认，不靠计时盲按 Space。"""
    def __init__(self, options: CraftOptions, now: float):
        options.validate()
        self.options, self.recipe = options, RECIPE_BY_KEY[options.recipe]
        self.phase = "inspect"
        self.submitted = self.collected = self.owned_in_queue = 0
        self.before_add = self.pending_owned = 0
        self.exhausted = self.finished = False
        self.queue_capacity = options.queue_capacity
        self.slots = ("unknown",) * self.queue_capacity
        self.message = "正在核对加工分类、队列格数与所有进度…"
        self.settle_until = now
        self.phase_since = now
        self.unrecognized_since: float | None = None
        self.expected_end = now
        self.last_confirmed_view = now
        self.open_retry_count = 0
        self._opening_slots = ()
        self._signature = None
        self._stable = 0

    @property
    def quota_reached(self) -> bool:
        return self.options.mode == "count" and self.submitted >= self.options.count

    def resume_after_pause(self, seconds: float) -> None:
        """保留次数和等待确认阶段；只顺延助手超时，游戏加工时间仍然流逝。"""
        for name in ("phase_since", "settle_until", "last_confirmed_view"):
            setattr(self, name, getattr(self, name) + seconds)
        if self.unrecognized_since is not None:
            self.unrecognized_since += seconds
        self._signature = None
        self._stable = 0
        self.message = "制作已继续，重新核对队列和上一次操作结果。"

    def progress(self, now: float, generation: int = 0) -> CraftProgress:
        return CraftProgress(self.phase, self.message, self.submitted, self.collected, self.slots,
                             max(0, self.expected_end - now), not self.finished, generation)

    def stop(self, message: str, *, error: bool = False) -> CraftDecision:
        self.finished = True
        self.phase = "error" if error else "done"
        self.message = message
        return CraftDecision(message=message)

    def _act(self, action: str, phase: str, message: str, now: float, point=None) -> CraftDecision:
        self.phase, self.message, self.phase_since = phase, message, now
        self.settle_until = now + 0.8
        self._stable = 0
        return CraftDecision(action, point, message)

    def step(self, view: CraftView, now: float) -> CraftDecision:
        if self.finished:
            return CraftDecision(message=self.message)
        if not view.result:
            self.slots = view.slots + ("unknown",) * max(0, self.queue_capacity-len(view.slots))
        # 强特征提示可能很短暂，收到即锁存，不再反复消耗材料/重试添加。
        if view.insufficient:
            self.exhausted = True
        if now < self.settle_until:
            return CraftDecision()
        if self.phase.startswith("await_") and now-self.phase_since > 15:
            reason = {"await_dialog": "点击材料后未打开详情", "await_add": "添加后未确认队列增加",
                      "await_result": "领取后未出现加工完成页", "await_return": "确认后未返回空队列",
                      "await_close": "关闭详情后未返回加工主界面"}.get(self.phase, "操作后未确认画面变化")
            return self.stop(f"{reason}，等待 15 秒后停止；请检查游戏响应。", error=True)
        if now-self.last_confirmed_view > 25:
            return self.stop("连续 25 秒未取得稳定的加工界面和队列，已停止。", error=True)
        signature = (view.category, view.slots, view.dialog_recipe, view.dialog_open,
                     view.result, bool(view.recipe_point), bool(view.collect_point), bool(view.process_point), view.queue_complete)
        self._stable = self._stable + 1 if signature == self._signature else 1
        self._signature = signature
        if self._stable < 2:
            return CraftDecision()
        known = (view.queue_complete and 0 < len(view.slots) <= MAX_QUEUE_CAPACITY
                 and all(state in {"empty", "busy", "complete"} for state in view.slots))
        if not view.result and view.category == self.recipe.category:
            if self.queue_capacity and len(view.slots) != self.queue_capacity:
                return self._wait_unclear(now, f"队列容量不一致：本次锁定 {self.queue_capacity} 格，当前识别 {len(view.slots)} 格；暂不操作。")
            if not self.queue_capacity and known:
                self.queue_capacity = len(view.slots)
                self.message = f"已连续确认队列容量 {self.queue_capacity} 格，本次任务锁定此容量。"
        if view.result or (view.category == self.recipe.category and known):
            self.last_confirmed_view = now

        if view.result:
            if self.phase == "await_return":
                if now-self.phase_since > 15:
                    return self.stop("领取确认后弹窗未关闭，已停止。", error=True)
                return CraftDecision()
            if self.phase != "await_result":
                return self.stop("出现了未预期的领取弹窗，请确认后从加工主界面重新开始。", error=True)
            return self._act("confirm", "await_return", "已识别加工完成，确认领取结果。", now)

        if view.category != self.recipe.category:
            if view.category:
                return self.stop(f"当前是{CATEGORIES[view.category]}，与所选{self.recipe.name}不符，已停止。", error=True)
            if self.unrecognized_since is None:
                self.unrecognized_since = now
            self.message = "未识别加工界面，暂不操作。请保持对应界面打开。"
            if now - self.unrecognized_since > 20:
                return self.stop("连续 20 秒未识别加工界面，已停止；不会切换界面或盲按按键。", error=True)
            return CraftDecision()
        self.unrecognized_since = None

        known = known and len(view.slots) == self.queue_capacity
        occupied = sum(s in {"busy", "complete"} for s in view.slots)
        if self.phase == "await_add":
            if known and occupied == self.before_add + 1:
                self.submitted += 1
                self.owned_in_queue += 1
                self.expected_end = max(now, self.expected_end) + self.recipe.seconds
                self.phase = "inspect"
                self.message = f"已确认加入第 {self.submitted} 次加工；当前队列 {occupied}/{self.queue_capacity}。"
                if view.dialog_open:
                    return self._act("close_dialog", "await_close", "添加已确认，返回加工队列。", now)
                return CraftDecision(message=self.message)
            if self.exhausted and known and occupied == self.before_add:
                self.phase = "inspect"
                if view.dialog_open:
                    return self._act("close_dialog", "await_close", "材料不足，不再添加；等待已有队列完成。", now)
            elif now - self.phase_since > 15:
                return self.stop("添加后未确认队列增加，已停止，避免重复添加导致次数超出。", error=True)
            else:
                self.message = "已发送添加，等待队列数量增加…"
                return CraftDecision()

        if self.phase in {"await_result", "await_return", "await_close"}:
            if self.phase == "await_return" and not view.dialog_open and known and occupied == 0:
                self.collected += self.pending_owned
                self.owned_in_queue = self.pending_owned = 0
                self.phase = "inspect"
                self.expected_end = now
            elif self.phase == "await_close" and not view.dialog_open:
                self.phase = "inspect"
            elif now - self.phase_since > 15:
                return self.stop("等待界面切换超时，已停止；请检查游戏是否响应。", error=True)
            else:
                return CraftDecision()

        if view.dialog_open:
            if view.dialog_recipe != self.options.recipe:
                recognized = RECIPE_BY_KEY.get(view.dialog_recipe)
                reason = (f"所选{self.recipe.name}，详情识别为{recognized.name}，配方不符"
                          if recognized else "未确认材料详情的名称和原料")
                return self.stop(reason + "，已停止，未按空格。", error=True)
            if self.exhausted:
                return self._act("close_dialog", "await_close", "材料不足，关闭材料详情，保留已有加工队列。", now)
            if self.phase != "await_dialog":
                return self.stop("请先关闭材料详情，在加工主界面开始任务。", error=True)
            if not known:
                return self._wait_unclear(now, "材料详情下的" + self._unclear_queue_message(view))
            if occupied >= self.queue_capacity or self.quota_reached:
                return self._act("close_dialog", "await_close", "队列已满或已达到次数，返回等待。", now)
            if not view.process_point:
                return self._wait_unclear(now, "未确认可用的加工按钮，暂不添加。")
            self.before_add = occupied
            return self._act("add", "await_add", f"确认配方：{self.recipe.name}，添加到第 {occupied + 1} 格。", now, view.process_point)

        if self.phase == "await_dialog":
            # 只重试不消耗材料的“打开详情”：连续确认仍在主界面、原队列未变。
            # 添加/领取/确认空格绝不重放；投递异常由 runner 直接停止。
            if (known and view.recipe_point and view.slots == self._opening_slots
                    and now-self.phase_since >= 3 and self.open_retry_count < 1):
                self.open_retry_count += 1
                return self._act("open_recipe", "await_dialog", "详情尚未打开，重新确认材料后补点一次。", now, view.recipe_point)
            return CraftDecision()
        if not known:
            return self._wait_unclear(now, self._unclear_queue_message(view))
        if occupied == 0 and (self.exhausted or self.quota_reached):
            reason = "材料不足，已有加工已领取。" if self.exhausted else "指定次数已完成并领取。"
            return self.stop(f"{reason} 本次添加 {self.submitted} 次，领取 {self.collected} 次。")
        if occupied < self.queue_capacity and not self.exhausted and not self.quota_reached:
            if not view.recipe_point:
                return self._wait_unclear(now, f"未找到所选材料“{self.recipe.name}”，不会改选其他材料。")
            self.open_retry_count = 0
            self._opening_slots = view.slots
            return self._act("open_recipe", "await_dialog", f"正在打开{self.recipe.name}，等待详情确认。", now, view.recipe_point)
        if occupied and all(s in {"empty", "complete"} for s in view.slots):
            if not view.collect_point:
                return self._wait_unclear(now, "进度已完成，等待确认“全部领取”按钮。")
            self.pending_owned = self.owned_in_queue
            return self._act("collect", "await_result", f"已连续确认 {occupied} 格均为 100%，全部领取。", now, view.collect_point)
        self.message = f"等待加工：{occupied}/{self.queue_capacity} 格，{view.slots.count('complete')} 格已到 100%。"
        self.phase_since = now
        return CraftDecision()

    def _unclear_queue_message(self, view: CraftView) -> str:
        if not view.queue_complete:
            reason = "队列边缘未确认，请检查底部和右侧是否被截断"
        elif not self.slots:
            reason = "尚未定位到队列，请保持加工主界面和全部队列格可见"
        else:
            indices = "、".join(str(i) for i, state in enumerate(self.slots, 1)
                               if state not in {"empty", "busy", "complete"})
            reason = f"第 {indices} 格状态待确认，请保持这些槽位完整可见"
        return f"队列尚未识别完整：{reason}；暂不操作。"

    def _wait_unclear(self, now: float, message: str) -> CraftDecision:
        self.message = message
        if now - self.phase_since > 20:
            return self.stop(message + " 连续未确认，已停止。", error=True)
        return CraftDecision()
