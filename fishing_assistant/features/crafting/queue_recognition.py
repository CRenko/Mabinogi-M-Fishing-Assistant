"""按领取锚点扫描多行队列；OK 百分比判断进度，圆环只证明槽位存在。"""
from __future__ import annotations

import numpy as np

from fishing_assistant.features.crafting.model import MAX_QUEUE_CAPACITY


QUEUE_COLUMNS = 4  # 当前布局每行四列，容量本身不固定为四。
SLOT_PITCH = 122


def _empty_slot_mask(template):
    """保留圆环和槽内下部，排除外部背景及可能透出加工设备的顶部。

    槽内材料/百分比仍参与匹配，不能只凭圆环存在判为空槽。
    """
    height, width = template.shape[:2]
    yy, xx = np.ogrid[:height, :width]
    radius_squared = ((xx-(width-1)/2)/width)**2 + ((yy-(height-1)/2)/height)**2
    return ((radius_squared <= .48**2) & (yy >= height*.30)).astype(np.uint8)*255


def _slot_state(vision, cx, cy, scale, scales):
    percent_area = (cx-45*scale, cy+3*scale, cx+46*scale, cy+47*scale)
    complete = vision._match("percent_100", percent_area, threshold=.86, scales=scales)
    if not complete:
        complete = vision._match("percent_100_white", percent_area, threshold=.82, scales=scales)
    if not complete:
        for key in ("percent_100_iron", "percent_100_cloth", "percent_100_silk"):
            complete = vision._match(key, percent_area, threshold=.86, scales=scales)
            if complete:
                break
    if complete:
        return "complete", True
    if vision._match("percent", percent_area, threshold=.77, scales=scales):
        return "busy", True
    area = (cx-68*scale, cy-70*scale, cx+70*scale, cy+70*scale)
    for key, threshold in (("empty", .88), ("empty_cloth", .89), ("empty_cloth_right", .89)):
        if vision._match(key, area, threshold=threshold, scales=scales):
            return "empty", True
    # 透明空槽会透出炉子等背景。通过 OK 的遮罩模板匹配排除这些干扰，
    # 使用更严格的分数，保留槽内材料检查，不把未知状态直接当成空槽。
    for key in ("empty", "empty_cloth", "empty_cloth_right"):
        if vision._match(key, area, threshold=.94, scales=scales, mask_function=_empty_slot_mask):
            return "empty", True
    # 遮住材料与文字，只匹配圆环。即使百分比模糊，存在的第五格也不能被丢弃。
    ring = vision._match("queue_ring", area, threshold=.65, scales=scales, ring_only=True)
    return "unknown", bool(ring)


def inspect_queue(vision, collect, scale, scales, expected_capacity=0):
    if collect is None:
        return ("unknown",)*expected_capacity, False
    height, width = vision.image.shape[:2]
    states, present, visible = [], [], []
    for index in range(MAX_QUEUE_CAPACITY):
        row, column = divmod(index, QUEUE_COLUMNS)
        cx = collect.x + (35+SLOT_PITCH*column)*collect.scale
        cy = collect.y + (112+SLOT_PITCH*row)*collect.scale
        # 不能把截图底部截断的槽当作不存在。
        fully_visible = cx-55*scale >= 0 and cy-55*scale >= 0 and cx+55*scale < width and cy+55*scale < height
        if row and column == 0 and cy-55*scale >= height:
            break
        state, exists = _slot_state(vision, cx, cy, scale, scales)
        states.append(state)
        present.append(exists)
        visible.append(fully_visible)
    found = max((index+1 for index, exists in enumerate(present) if exists), default=0)
    # 从一格起计数，只扩展到有槽位证据的位置；中间缺格保留 unknown。
    capacity = max(found, expected_capacity)
    states += ["unknown"]*max(0, capacity-len(states))
    visible += [False]*max(0, capacity-len(visible))
    return tuple(states[:capacity]), bool(capacity and all(visible[:capacity]))
