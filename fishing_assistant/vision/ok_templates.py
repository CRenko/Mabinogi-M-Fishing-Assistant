"""OK FeatureSet 模板缓存、多尺度扫描及背包／鱼竿提示识别"""
from __future__ import annotations

import cv2
import numpy as np
from fishing_assistant.constants import (
    FISH_ESCAPE_TEMPLATE_PATH,
    INVENTORY_FULL_ICON_TEMPLATE_PATH,
    INVENTORY_FULL_TEMPLATE_PATH,
    ROD_REQUIRED_TEMPLATE_PATH,
)
from ok.feature.FeatureSet import FeatureSet
from pathlib import Path


class OkTemplateRecognitionMixin:
    """OK FeatureSet 模板缓存、多尺度扫描及背包／鱼竿提示识别；由 FishingEngine 组装，不单独实例化。"""

    @staticmethod
    def _white_text_mask(bgr: np.ndarray) -> np.ndarray:
        """提取游戏提示中的低饱和高亮文字，忽略动态场景颜色。"""
        hsv = cv2.cvtColor(bgr[:, :, :3], cv2.COLOR_BGR2HSV)
        return cv2.inRange(
            hsv, np.array([0, 0, 180]), np.array([179, 105, 255])
        )

    @classmethod
    def _load_text_template(cls, path: Path) -> np.ndarray | None:
        template = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if template is None:
            return None
        # 颜色仅用于从静态素材中裁出文字；运行时识别交给 OK FeatureSet。
        mask = cls._white_text_mask(template)
        points = cv2.findNonZero(mask)
        if points is None:
            return None
        x, y, width, height = cv2.boundingRect(points)
        padding = 8
        left = max(0, x - padding)
        top = max(0, y - padding)
        right = min(template.shape[1], x + width + padding)
        bottom = min(template.shape[0], y + height + padding)
        return template[top:bottom, left:right, :3]

    @classmethod
    def _load_escape_template_mask(cls) -> np.ndarray | None:
        if cls._escape_template_mask is None:
            cls._escape_template_mask = cls._load_text_template(
                FISH_ESCAPE_TEMPLATE_PATH
            )
        return cls._escape_template_mask

    @classmethod
    def _load_rod_required_template_mask(cls) -> np.ndarray | None:
        if cls._rod_required_template_mask is None:
            cls._rod_required_template_mask = cls._load_text_template(
                ROD_REQUIRED_TEMPLATE_PATH
            )
        return cls._rod_required_template_mask

    @classmethod
    def _load_inventory_full_template_mask(cls) -> np.ndarray | None:
        if cls._inventory_full_template_mask is None:
            cls._inventory_full_template_mask = cls._load_text_template(
                INVENTORY_FULL_TEMPLATE_PATH
            )
        return cls._inventory_full_template_mask

    @classmethod
    def _get_ok_feature_set(cls) -> FeatureSet:
        if cls._ok_feature_set is None:
            cls._ok_feature_set = FeatureSet(
                False,
                "__direct_templates__.json",
                default_horizontal_variance=0,
                default_vertical_variance=0,
                default_threshold=0.80,
            )
        return cls._ok_feature_set

    @classmethod
    def _category_scan_scales(
        cls, category_name: str, scales: np.ndarray
    ) -> np.ndarray:
        """只有该模板自己命中过才限缩扫描范围；不跨模板推断尺度。"""
        hint = cls._scale_hints.get(category_name)
        if hint is None or (
            cls._no_decision_streak > 0
            and cls._no_decision_streak % cls.OK_SCALE_RESCAN_EVERY == 0
        ):
            return scales
        nearest = sorted(
            (float(scale) for scale in scales),
            key=lambda scale: abs(scale - hint),
        )[: cls.OK_SCALE_LOCK_NEIGHBORS]
        return np.array(sorted(nearest))

    @classmethod
    def _note_icon_decision(cls) -> None:
        cls._no_decision_streak = 0

    @classmethod
    def _ordered_scales(
        cls, category_name: str, scales: np.ndarray
    ) -> list[float]:
        """把上次命中的尺度排到最前面，让稳定会话第一次尝试就命中。"""
        values = [float(scale) for scale in scales]
        hint = cls._scale_hints.get(category_name)
        if hint is None:
            return values
        return sorted(values, key=lambda scale: abs(scale - hint))

    @classmethod
    def _ok_multiscale_confidence(
        cls,
        bgr: np.ndarray,
        template: np.ndarray | None,
        *,
        search_top_ratio: float,
        search_bottom_ratio: float,
        scales: np.ndarray,
        normalized_width: int,
        baseline_scale: float,
        category_name: str,
        use_gray_scale: bool = True,
        early_exit_confidence: float | None = None,
        hint_floor: float | None = None,
    ) -> float:
        """通过 OK FeatureSet 在指定区域执行多尺度灰度模板识别。"""
        if (
            template is None
            or bgr.ndim != 3
            or bgr.shape[0] < 20
            or bgr.shape[1] < 20
        ):
            return 0.0

        frame_height, frame_width = bgr.shape[:2]
        normalized_height = max(
            1, round(frame_height * normalized_width / frame_width)
        )
        normalized = cv2.resize(
            bgr[:, :, :3],
            (normalized_width, normalized_height),
            interpolation=cv2.INTER_AREA,
        )
        baseline = cv2.resize(
            template,
            (
                max(1, round(template.shape[1] * baseline_scale)),
                max(1, round(template.shape[0] * baseline_scale)),
            ),
            interpolation=cv2.INTER_AREA,
        )
        search_height = max(
            1,
            round(normalized_height * (search_bottom_ratio - search_top_ratio)),
        )
        feature_set = cls._get_ok_feature_set()
        best = 0.0
        best_scale: float | None = None
        for scale in cls._ordered_scales(category_name, scales):
            candidate = cv2.resize(
                baseline,
                (
                    max(1, round(baseline.shape[1] * scale)),
                    max(1, round(baseline.shape[0] * scale)),
                ),
                interpolation=cv2.INTER_AREA,
            )
            if (
                candidate.shape[0] > search_height
                or candidate.shape[1] > normalized_width
            ):
                continue
            boxes = feature_set.find_one_feature(
                mat=normalized,
                category_name=category_name,
                threshold=-1.0,
                use_gray_scale=use_gray_scale,
                x=0.0,
                y=search_top_ratio,
                width=1.0,
                height=search_bottom_ratio - search_top_ratio,
                template=candidate,
                limit=1,
            )
            if boxes:
                confidence = float(boxes[0].confidence)
                if confidence > best:
                    best = confidence
                    best_scale = scale
                if (
                    early_exit_confidence is not None
                    and best >= early_exit_confidence
                ):
                    break
        record_floor = (
            hint_floor if hint_floor is not None else cls.OK_SCALE_HINT_MIN_CONFIDENCE
        )
        if best_scale is not None and best >= record_floor:
            cls._scale_hints[category_name] = best_scale
        return best

    @classmethod
    def _text_template_confidence(
        cls,
        bgr: np.ndarray,
        template: np.ndarray | None,
        *,
        search_top_ratio: float,
        search_bottom_ratio: float,
        scales: np.ndarray,
        category_name: str = "runtime_text_template",
        early_exit_confidence: float | None = None,
    ) -> float:
        return cls._ok_multiscale_confidence(
            bgr,
            template,
            search_top_ratio=search_top_ratio,
            search_bottom_ratio=search_bottom_ratio,
            scales=scales,
            normalized_width=960,
            baseline_scale=0.5,
            category_name=category_name,
            early_exit_confidence=early_exit_confidence,
        )

    @classmethod
    def fish_escape_message_confidence(cls, bgr: np.ndarray) -> float:
        """用固定文字模板识别“猶豫了一下，結果讓牠跑掉了……”提示。"""
        return cls._text_template_confidence(
            bgr,
            cls._load_escape_template_mask(),
            search_top_ratio=0.25,
            search_bottom_ratio=1.0,
            scales=np.linspace(0.80, 1.20, 9),
            category_name="text_fish_escape",
            early_exit_confidence=cls.ESCAPE_MESSAGE_MATCH_THRESHOLD,
        )

    @classmethod
    def rod_required_message_confidence(cls, bgr: np.ndarray) -> float:
        """识别画面上方的“必須配戴釣竿。”提示。"""
        return cls._text_template_confidence(
            bgr,
            cls._load_rod_required_template_mask(),
            search_top_ratio=0.0,
            search_bottom_ratio=0.45,
            scales=np.linspace(0.75, 1.30, 12),
            category_name="text_rod_required",
            early_exit_confidence=cls.ROD_REQUIRED_MATCH_THRESHOLD,
        )

    @classmethod
    def inventory_full_message_confidence(cls, bgr: np.ndarray) -> float:
        """识别画面上方的“請整理背包後再試一次。”提示。"""
        return cls._text_template_confidence(
            bgr,
            cls._load_inventory_full_template_mask(),
            search_top_ratio=0.0,
            search_bottom_ratio=0.45,
            scales=np.linspace(0.75, 1.30, 12),
            category_name="text_inventory_full",
            early_exit_confidence=cls.INVENTORY_FULL_MATCH_THRESHOLD,
        )

    @classmethod
    def _load_inventory_full_icon_template(cls) -> np.ndarray | None:
        if cls._inventory_full_icon_template is None:
            image = cv2.imread(
                str(INVENTORY_FULL_ICON_TEMPLATE_PATH), cv2.IMREAD_COLOR
            )
            if image is not None:
                height, width = image.shape[:2]
                # 静态样本左侧为红圈背包；排除右侧钓鱼按钮与大部分地面。
                cls._inventory_full_icon_template = image[
                    round(height * 0.18) : round(height * 0.94),
                    0 : round(width * 0.38),
                    :3,
                ]
        return cls._inventory_full_icon_template

    @classmethod
    def inventory_full_icon_confidence(cls, bgr: np.ndarray) -> float:
        """用 OK 彩色特征识别钓鱼按钮左侧的红圈背包。"""
        return cls._ok_multiscale_confidence(
            bgr,
            cls._load_inventory_full_icon_template(),
            search_top_ratio=0.25,
            search_bottom_ratio=1.0,
            scales=np.linspace(0.70, 1.35, 14),
            normalized_width=960,
            baseline_scale=0.5,
            category_name="inventory_full_icon",
            use_gray_scale=False,
            early_exit_confidence=cls.INVENTORY_FULL_ICON_MATCH_THRESHOLD,
        )
