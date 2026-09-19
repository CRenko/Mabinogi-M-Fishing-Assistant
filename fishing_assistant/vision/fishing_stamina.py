"""中鱼锚点、动态体力槽及槽中点状态识别"""
from __future__ import annotations

import cv2
import numpy as np
from dataclasses import replace
from fishing_assistant.automation.models import StaminaBarSample, StaminaMidpointState
from fishing_assistant.constants import OK_STAMINA_ANCHOR_TEMPLATE_PATH
from fishing_assistant.vision.stamina import find_stamina_bar_v2


class FishingStaminaRecognitionMixin:
    """中鱼锚点、动态体力槽及槽中点状态识别；由 FishingEngine 组装，不单独实例化。"""

    def _find_stamina_bar_v2_sample(
        self, game_frame: np.ndarray
    ) -> StaminaBarSample | None:
        """v2 读条定位结果转引擎采样结构；失败返回 None，绝不抛异常。"""
        try:
            bar = find_stamina_bar_v2(
                game_frame, last_center=self._stamina_last_center
            )
        except Exception:
            return None
        if bar is None:
            return None
        return StaminaBarSample(
            bar.fill_width,
            bar.center,
            bar.anchor_confidence,
            fill_left=bar.fill_left,
            fill_height=bar.fill_height,
        )

    @classmethod
    def _load_stamina_anchor_template(cls) -> np.ndarray | None:
        if cls._stamina_anchor_template is None:
            cls._stamina_anchor_template = cv2.imread(
                str(OK_STAMINA_ANCHOR_TEMPLATE_PATH), cv2.IMREAD_COLOR
            )
        return cls._stamina_anchor_template

    @classmethod
    def _stamina_anchor_confidence(
        cls,
        bgr: np.ndarray,
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> float:
        """在绿条上方用 OK 彩色特征确认随角色移动的中鱼圆形图标。"""
        template = cls._load_stamina_anchor_template()
        if template is None:
            return 0.0
        frame_height, frame_width = bgr.shape[:2]
        horizontal_span = max(140, min(420, width * 4))
        vertical_span = max(80, min(240, height * 8))
        left = max(0, x - round(horizontal_span * 0.25))
        right = min(frame_width, x + horizontal_span)
        top = max(0, y - vertical_span)
        bottom = min(frame_height, y + max(2, height // 3))
        if right - left < 20 or bottom - top < 20:
            return 0.0
        search = bgr[top:bottom, left:right, :3]
        return cls._ok_multiscale_confidence(
            search,
            template,
            search_top_ratio=0.0,
            search_bottom_ratio=1.0,
            scales=np.array(
                [0.65, 0.75, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.20, 1.35, 1.55]
            ),
            normalized_width=search.shape[1],
            baseline_scale=1.0,
            category_name="stamina_fish_anchor",
            use_gray_scale=False,
            early_exit_confidence=cls.STAMINA_ANCHOR_MATCH_THRESHOLD,
        )

    @classmethod
    def find_stamina_bar(
        cls,
        bgr: np.ndarray,
        *,
        require_anchor: bool = False,
        preferred_center: tuple[int, int] | None = None,
    ) -> StaminaBarSample | None:
        """全画面寻找绿条；实机模式再用其上方的中鱼图标作 OK 锚点确认。"""
        if bgr.ndim != 3 or bgr.shape[0] <= 0 or bgr.shape[1] <= 0:
            return None
        hsv = cv2.cvtColor(bgr[:, :, :3], cv2.COLOR_BGR2HSV)
        green_mask = cv2.inRange(
            hsv, np.array([35, 60, 70]), np.array([100, 255, 255])
        )
        green_mask = cv2.morphologyEx(
            green_mask, cv2.MORPH_OPEN, np.ones((2, 2), dtype=np.uint8)
        )
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
            green_mask, connectivity=8
        )
        # 绿条会跟随角色在整张画面中移动。先按细长填充和深色槽体找候选，
        # 再用候选上方的中鱼圆形图标做 OK 特征确认，不锁定屏幕坐标。
        dark_mask = cv2.inRange(hsv, np.array([0, 0, 0]), np.array([179, 255, 90]))
        frame_height, frame_width = bgr.shape[:2]
        candidates: list[tuple[StaminaBarSample, float, bool]] = []
        for index in range(1, count):
            x, y, width, height, area = (int(value) for value in stats[index])
            if not (24 <= width <= 480 and 5 <= height <= 32):
                continue
            if width < height * 2 or area < width * height * 0.55:
                continue
            # 绿色填充右边应当是尚未消耗的深色进度槽。用条内中段避免圆角和描边干扰。
            core_top = y + max(1, height // 4)
            core_bottom = min(frame_height, y + height - max(1, height // 4))
            track_depth = min(240, max(24, width * 2))
            right = min(frame_width, x + width + track_depth)
            right_band = dark_mask[core_top:core_bottom, x + width : right]
            right_dark_ratio = (
                float(cv2.countNonZero(right_band)) / max(1, right_band.size)
            )
            # 满体力时右侧空槽很短，因此保留上下深色描边作为弱结构特征。
            border_top = dark_mask[max(0, y - 3) : y, x : x + width]
            border_bottom = dark_mask[
                y + height : min(frame_height, y + height + 3), x : x + width
            ]
            border_size = border_top.size + border_bottom.size
            border_dark_ratio = (
                float(cv2.countNonZero(border_top) + cv2.countNonZero(border_bottom))
                / max(1, border_size)
            )
            track_score = right_dark_ratio * 2.0 + border_dark_ratio * 0.35
            anchor_confidence = (
                cls._stamina_anchor_confidence(bgr, x, y, width, height)
                if require_anchor
                else 1.0
            )
            if (
                require_anchor
                and anchor_confidence < cls.STAMINA_ANCHOR_MATCH_THRESHOLD
            ):
                continue
            sample = StaminaBarSample(
                width,
                (x + width // 2, y + height // 2),
                anchor_confidence,
                fill_left=x,
                fill_height=height,
            )
            in_focus_area = (
                frame_width * 0.20 <= sample.center[0] <= frame_width * 0.80
                and frame_height * 0.10 <= sample.center[1] <= frame_height * 0.65
            )
            candidates.append((sample, track_score, in_focus_area))
        if not candidates:
            return None
        # OK 锚点优先；中部位置和填充宽度只在相似度接近时作弱排序。
        sample, _track_score, _in_focus = max(
            candidates,
            key=lambda item: (
                item[0].anchor_confidence,
                (
                    -float(
                        np.hypot(
                            item[0].center[0] - preferred_center[0],
                            item[0].center[1] - preferred_center[1],
                        )
                    )
                    if preferred_center is not None
                    else item[1]
                ),
                item[1],
                0.10 if item[2] else 0.0,
                item[0].fill_width,
            ),
        )
        return sample

    @classmethod
    def classify_stamina_midpoint(
        cls,
        bgr: np.ndarray,
        sample: StaminaBarSample,
        probe_offset_x: int,
    ) -> StaminaBarSample:
        """读取进度槽半条位置的小块颜色，避免用整段绿条宽度猜反弹。"""
        if bgr.ndim != 3 or bgr.shape[0] <= 0 or bgr.shape[1] <= 0:
            return sample
        left = (
            sample.fill_left
            if sample.fill_left is not None
            else sample.center[0] - sample.fill_width // 2
        )
        probe_x = left + max(1, int(probe_offset_x))
        probe_y = sample.center[1]
        radius = max(2, min(6, round(max(7, sample.fill_height) * 0.22)))
        frame_height, frame_width = bgr.shape[:2]
        left_edge = max(0, probe_x - radius)
        right_edge = min(frame_width, probe_x + radius + 1)
        top_edge = max(0, probe_y - radius)
        bottom_edge = min(frame_height, probe_y + radius + 1)
        if right_edge <= left_edge or bottom_edge <= top_edge:
            return sample

        probe = bgr[top_edge:bottom_edge, left_edge:right_edge, :3]
        hsv = cv2.cvtColor(probe, cv2.COLOR_BGR2HSV)
        green_mask = cv2.inRange(
            hsv, np.array([35, 60, 70]), np.array([100, 255, 255])
        )
        dark_mask = cv2.inRange(
            hsv, np.array([0, 0, 0]), np.array([179, 255, 110])
        )
        area = max(1, green_mask.size)
        green_ratio = float(cv2.countNonZero(green_mask)) / area
        dark_ratio = float(cv2.countNonZero(dark_mask)) / area
        if green_ratio >= cls.STAMINA_MIDPOINT_GREEN_RATIO:
            state = StaminaMidpointState.GREEN
        elif dark_ratio >= cls.STAMINA_MIDPOINT_DARK_RATIO:
            state = StaminaMidpointState.DARK
        else:
            state = StaminaMidpointState.UNKNOWN
        return replace(
            sample,
            midpoint_state=state,
            midpoint_green_ratio=green_ratio,
            midpoint_dark_ratio=dark_ratio,
        )
