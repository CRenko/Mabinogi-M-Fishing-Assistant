"""钓鱼图标分类、OK 图标匹配与用户选择的像素兼容识别"""
from __future__ import annotations

import cv2
import numpy as np
from dataclasses import replace
from fishing_assistant.automation.models import IconColorSignals, IconState
from fishing_assistant.config import AppConfig
from fishing_assistant.constants import OK_ICON_TEMPLATE_PATHS, OK_IDLE_MOTION_TEMPLATE_PATH
from fishing_assistant.vision import signature as vision_signature
from pathlib import Path


class FishingIconRecognitionMixin:
    """钓鱼图标分类、OK 图标匹配与用户选择的像素兼容识别；由 FishingEngine 组装，不单独实例化。"""

    @staticmethod
    def _icon_circle_mask(height: int, width: int) -> np.ndarray:
        mask = np.zeros((height, width), dtype=np.uint8)
        cv2.ellipse(
            mask,
            (width // 2, height // 2),
            (int(width * 0.46), int(height * 0.43)),
            0,
            0,
            360,
            255,
            -1,
        )
        return mask

    @classmethod
    def analyze_icon_colors(cls, bgr: np.ndarray) -> IconColorSignals:
        """统计圆形按钮内的红、白、绿、棕比例，用于钓鱼和骑马图标识别。"""
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        low_red = cv2.inRange(
            hsv, np.array([0, 105, 95]), np.array([15, 255, 255])
        )
        high_red = cv2.inRange(
            hsv, np.array([165, 105, 95]), np.array([179, 255, 255])
        )
        red_mask = cv2.bitwise_or(low_red, high_red)
        white_mask = cv2.inRange(hsv, np.array([0, 0, 180]), np.array([179, 55, 255]))
        green_mask = cv2.inRange(hsv, np.array([35, 55, 80]), np.array([95, 255, 255]))
        blue_mask = cv2.inRange(hsv, np.array([88, 60, 70]), np.array([132, 255, 255]))
        brown_mask = cv2.inRange(hsv, np.array([5, 65, 60]), np.array([28, 255, 255]))
        circle_mask = cls._icon_circle_mask(*red_mask.shape)
        area = max(1, int(cv2.countNonZero(circle_mask)))

        def ratio(mask: np.ndarray) -> float:
            return cv2.countNonZero(cv2.bitwise_and(mask, circle_mask)) / area

        red_ratio = ratio(red_mask)
        return IconColorSignals(
            red_pixels=int(round(red_ratio * area)),
            red_ratio=red_ratio,
            white_ratio=ratio(white_mask),
            green_ratio=ratio(green_mask),
            blue_ratio=ratio(blue_mask),
            brown_ratio=ratio(brown_mask),
        )

    @classmethod
    def compass_pixel_confidence(cls, bgr: np.ndarray) -> float:
        """在按钮中心附近搜索旋转不变的黑色圆点，并以指针配色复核。"""
        if bgr.ndim != 3 or bgr.shape[0] < 20 or bgr.shape[1] < 20:
            return 0.0
        cropped = cls._crop_ok_icon_image(bgr[:, :, :3])
        normalized = cv2.resize(cropped, (128, 128), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(normalized, cv2.COLOR_BGR2HSV)
        hue, saturation, value = cv2.split(hsv)

        black_mask = (value <= 45).astype(np.uint8)
        count, _labels, stats, centroids = cv2.connectedComponentsWithStats(
            black_mask, 8
        )
        best_dot_area = 0
        for component in range(1, count):
            x, y, width, height, area = (
                int(item) for item in stats[component, :5]
            )
            center_x, center_y = (float(item) for item in centroids[component])
            fill_ratio = area / max(1, width * height)
            aspect_ratio = width / max(1, height)
            if (
                35 <= center_x <= 93
                and 35 <= center_y <= 93
                and 60 <= area <= 320
                and 8 <= width <= 26
                and 8 <= height <= 26
                and 0.50 <= fill_ratio <= 1.0
                and 0.55 <= aspect_ratio <= 1.80
            ):
                best_dot_area = max(best_dot_area, area)

        red_ratio = float(
            (
                ((hue <= 12) | (hue >= 170))
                & (saturation >= 90)
                & (value >= 90)
            ).mean()
        )
        white_ratio = float(((saturation <= 45) & (value >= 180)).mean())
        green_ratio = float(
            (
                (hue >= 35)
                & (hue <= 100)
                & (saturation >= 55)
                & (value >= 70)
            ).mean()
        )
        dot_confidence = min(1.0, best_dot_area / 120)
        if (
            dot_confidence >= cls.COMPASS_PIXEL_MATCH_THRESHOLD
            and 0.008 <= red_ratio <= 0.045
            and 0.035 <= white_ratio <= 0.16
            and 0.15 <= green_ratio <= 0.52
        ):
            return dot_confidence
        return 0.0

    @classmethod
    def count_fish_red_pixels(cls, bgr: np.ndarray) -> int:
        """兼容既有调用：只返回圆形按钮内的红橙色像素数。"""
        return cls.analyze_icon_colors(bgr).red_pixels

    @staticmethod
    def classify_icon_state(red_pixels: int, config: AppConfig) -> IconState:
        """区分上钩鱼体、原地失效指针和普通抛竿/等待图标。"""
        if red_pixels >= config.fish_red_pixel_threshold:
            return IconState.FISH_HOOKED
        if config.idle_red_pixel_min <= red_pixels <= config.idle_red_pixel_max:
            return IconState.IDLE_RECOVERY
        if config.idle_red_pixel_max < red_pixels < config.fish_red_pixel_threshold:
            return IconState.READY_TO_CAST
        return IconState.NORMAL

    @classmethod
    def classify_frame_state(
        cls, bgr: np.ndarray, config: AppConfig
    ) -> tuple[IconState, IconColorSignals]:
        """运行所选识别后端；OK 模式仅对旋转指南针使用专用像素校正。"""
        if config.recognition_backend != "pixel":
            # 指南针会持续旋转，先用中心黑点与固定配色判定；其他图标仍交给 OK。
            signals = IconColorSignals(0, 0.0, 0.0, 0.0, 0.0, 0.0)
            compass_confidence = cls.compass_pixel_confidence(bgr)
            if compass_confidence:
                return IconState.IDLE_RECOVERY, replace(
                    signals,
                    recognition_source="compass_pixel",
                    recognition_confidence=compass_confidence,
                )
            if config.v2_vision_enabled:
                v2_state, v2_confidence = cls._v2_signature_match(bgr)
                if v2_state is not None:
                    return v2_state, replace(
                        signals,
                        recognition_source="v2_signature",
                        recognition_confidence=v2_confidence,
                    )
            # 签名 unknown（或 v2 关闭）时由 FeatureSet 模板仲裁。
            try:
                state, best_confidence, _second_confidence = (
                    cls.ok_icon_state_match(bgr)
                )
            except Exception:
                state, best_confidence = None, 0.0
            return state or IconState.NORMAL, replace(
                signals,
                recognition_source="ok_feature",
                recognition_confidence=best_confidence,
            )

        signals = cls.analyze_icon_colors(bgr)
        is_horse_icon = (
            signals.white_ratio >= 0.10
            and signals.green_ratio >= 0.38
            and 0.01 <= signals.brown_ratio <= 0.035
        )
        if is_horse_icon:
            state = (
                IconState.HORSE_DISMOUNT_PROMPT
                if signals.red_ratio >= 0.015
                else IconState.HORSE_MOUNT_PROMPT
            )
            return state, signals
        is_ready_rod = (
            signals.blue_ratio >= 0.14
            and signals.brown_ratio >= 0.015
            and signals.red_ratio < 0.085
        )
        if is_ready_rod:
            return IconState.READY_TO_CAST, signals

        state = cls.classify_icon_state(signals.red_pixels, config)
        if (
            state == IconState.NORMAL
            and signals.white_ratio >= 0.12
            and signals.green_ratio >= 0.45
            and signals.brown_ratio < 0.01
        ):
            state = IconState.WAITING_BITE
        return state, signals

    @classmethod
    def _v2_signature_match(cls, bgr: np.ndarray) -> tuple[IconState | None, float]:
        """v2 签名快判；无法确定时返回 None 交给模板仲裁层，绝不抛异常。"""
        try:
            circle = vision_signature.locate_button_in_roi(bgr)
            if circle is None:
                return None, 0.0
            cx, cy, radius = circle
            features = vision_signature.extract_signature(bgr, cx, cy, 2 * radius)
            state, confidence = vision_signature.classify_signature(features)
            if state == "unknown":
                return None, 0.0
            return IconState(state), confidence
        except Exception:
            return None, 0.0

    @staticmethod
    def _crop_ok_icon_image(image: np.ndarray) -> np.ndarray:
        """裁出圆形按钮核心，排除动态地面和 Space 标签。"""
        hsv = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2HSV)
        green = cv2.inRange(hsv, np.array([35, 45, 55]), np.array([100, 255, 255]))
        blue = cv2.inRange(hsv, np.array([90, 45, 55]), np.array([132, 255, 255]))
        mask = cv2.bitwise_or(green, blue)
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_CLOSE, np.ones((7, 7), dtype=np.uint8)
        )
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask)
        if count <= 1:
            return image[:, :, :3]
        component = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        x, y, width, height = (int(value) for value in stats[component, :4])
        left = x + round(width * 0.12)
        right = x + round(width * 0.86)
        top = y + round(height * 0.08)
        bottom = y + round(height * 0.90)
        if right <= left or bottom <= top:
            return image[:, :, :3]
        return image[top:bottom, left:right, :3]

    @classmethod
    def _load_ok_icon_template(cls, path: Path) -> np.ndarray | None:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            return None
        return cls._crop_ok_icon_image(image)

    @classmethod
    def _get_ok_icon_templates(cls) -> dict[str, np.ndarray]:
        if cls._ok_icon_templates is None:
            templates: dict[str, np.ndarray] = {}
            for state_name, path in OK_ICON_TEMPLATE_PATHS.items():
                template = cls._load_ok_icon_template(path)
                if template is not None:
                    templates[state_name] = template
            cls._ok_icon_templates = templates
        return cls._ok_icon_templates

    @staticmethod
    def _rotate_ok_template(template: np.ndarray, angle: float) -> np.ndarray:
        height, width = template.shape[:2]
        matrix = cv2.getRotationMatrix2D(
            (width / 2.0, height / 2.0), angle, 1.0
        )
        return cv2.warpAffine(
            template,
            matrix,
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT_101,
        )

    @classmethod
    def _get_ok_idle_rotated_templates(cls) -> tuple[np.ndarray, ...]:
        if cls._ok_idle_rotated_templates is None:
            templates: list[np.ndarray] = []
            if OK_IDLE_MOTION_TEMPLATE_PATH.exists():
                capture = cv2.VideoCapture(str(OK_IDLE_MOTION_TEMPLATE_PATH))
                frame_index = 0
                try:
                    while True:
                        success, frame = capture.read()
                        if not success:
                            break
                        # 真实 GIF 共 180 帧；每 12 帧取一个方向，覆盖指针旋转和轻微动画。
                        if frame_index % 12 == 0:
                            templates.append(cls._crop_ok_icon_image(frame))
                        frame_index += 1
                finally:
                    capture.release()
            if not templates:
                # 资源缺失时仍保留合成旋转模板，避免整个指南针恢复功能失效。
                base = cls._get_ok_icon_templates().get("idle_recovery")
                if base is not None:
                    height, width = base.shape[:2]
                    side = max(height, width)
                    top = (side - height) // 2
                    bottom = side - height - top
                    left = (side - width) // 2
                    right = side - width - left
                    square = cv2.copyMakeBorder(
                        base,
                        top,
                        bottom,
                        left,
                        right,
                        cv2.BORDER_REFLECT_101,
                    )
                    templates.extend(
                        cls._rotate_ok_template(square, angle)
                        for angle in range(0, 360, 15)
                    )
            cls._ok_idle_rotated_templates = tuple(templates)
        return cls._ok_idle_rotated_templates

    @classmethod
    def _get_ok_idle_center_template(cls) -> np.ndarray | None:
        """合成不受指针旋转影响的指南针中心黑点锚点。"""
        if cls._ok_idle_center_template is None:
            anchors: list[np.ndarray] = []
            for template in cls._get_ok_idle_rotated_templates():
                height, width = template.shape[:2]
                side = max(12, round(min(height, width) * 0.32))
                center_x = width // 2
                center_y = height // 2
                left = max(0, center_x - side // 2)
                top = max(0, center_y - side // 2)
                anchor = template[top : top + side, left : left + side]
                if anchor.size:
                    anchors.append(
                        cv2.resize(anchor, (48, 48), interpolation=cv2.INTER_AREA)
                    )
            if anchors:
                cls._ok_idle_center_template = np.mean(
                    np.stack(anchors), axis=0
                ).astype(np.uint8)
        return cls._ok_idle_center_template

    @classmethod
    def _score_icon_templates(
        cls, bgr: np.ndarray, scales_override: np.ndarray | None = None
    ) -> list[tuple[IconState, float]]:
        scores: list[tuple[IconState, float]] = []
        for state_name, template in cls._get_ok_icon_templates().items():
            scales = (
                scales_override
                if scales_override is not None
                else cls._category_scan_scales(
                    f"icon_{state_name}", cls.OK_ICON_FULL_SCALES
                )
            )
            try:
                confidence = cls._ok_multiscale_confidence(
                    bgr,
                    template,
                    search_top_ratio=0.0,
                    search_bottom_ratio=1.0,
                    scales=scales,
                    normalized_width=cls.OK_ICON_NORMALIZED_WIDTH,
                    baseline_scale=1.0,
                    category_name=f"icon_{state_name}",
                    hint_floor=cls.OK_ICON_HINT_MIN_CONFIDENCE,
                )
                scores.append((IconState(state_name), confidence))
            except (ValueError, cv2.error):
                continue
        return scores

    @classmethod
    def _decide_icon(
        cls, scores: list[tuple[IconState, float]]
    ) -> tuple[IconState | None, float, float]:
        ordered = sorted(scores, key=lambda item: item[1], reverse=True)
        best_state, best_confidence = ordered[0]
        second_confidence = ordered[1][1] if len(ordered) > 1 else 0.0
        if (
            best_confidence >= cls.OK_ICON_MATCH_THRESHOLD
            and best_confidence - second_confidence >= cls.OK_ICON_MATCH_MARGIN
        ):
            return best_state, best_confidence, second_confidence
        return None, best_confidence, second_confidence

    @classmethod
    def ok_icon_state_match(
        cls, bgr: np.ndarray
    ) -> tuple[IconState | None, float, float]:
        """返回 OK 状态及分数；未过阈值时保留分数但状态为空。"""
        scores = cls._score_icon_templates(bgr)
        if not scores:
            return None, 0.0, 0.0
        decided, best_confidence, second_confidence = cls._decide_icon(scores)
        restricted_active = bool(cls._scale_hints)
        full_rescanned = False
        if (
            decided is not None
            and restricted_active
            and decided != cls._last_decided_state
        ):
            # 限缩扫描下的「转态判定」必须全幅复验：限缩可能压低真状态、
            # 放行错状态，而按错键正是转态时才会发生。以全幅结果为准。
            scores = cls._score_icon_templates(
                bgr, scales_override=cls.OK_ICON_FULL_SCALES
            )
            decided, best_confidence, second_confidence = cls._decide_icon(
                scores
            )
            full_rescanned = True
        if (
            decided is None
            and restricted_active
            and not full_rescanned
            and best_confidence >= cls.OK_SCALE_RETRY_MIN_CONFIDENCE
        ):
            # 近判定却失败：可能吃了尺度限缩的亏，当帧全范围重扫一次。
            scores = cls._score_icon_templates(
                bgr, scales_override=cls.OK_ICON_FULL_SCALES
            )
            decided, best_confidence, second_confidence = cls._decide_icon(
                scores
            )
        if decided is not None:
            cls._last_decided_state = decided
            cls._note_icon_decision()
            return decided, best_confidence, second_confidence

        # 指南针指针会随人物方向旋转。普通模板未过门槛时，再用 GIF 真实方向帧复核；
        # 仍由 OK FeatureSet 完成匹配，不借用旧像素规则。
        idle_confidence = max(
            (
                confidence
                for state, confidence in scores
                if state == IconState.IDLE_RECOVERY
            ),
            default=0.0,
        )
        non_idle_confidence = max(
            (
                confidence
                for state, confidence in scores
                if state != IconState.IDLE_RECOVERY
            ),
            default=0.0,
        )
        rotated_full_scales = np.array(
            [0.72, 0.75, 0.78, 0.81, 0.86, 0.94, 1.02, 1.10, 1.18]
        )
        for index, template in enumerate(cls._get_ok_idle_rotated_templates()):
            # 判定条件一旦满足就停止扫描剩余方向帧：结论不变，成本立减。
            if (
                idle_confidence >= cls.OK_IDLE_ROTATED_MATCH_THRESHOLD
                and idle_confidence - non_idle_confidence
                >= cls.OK_IDLE_ROTATED_MATCH_MARGIN
            ):
                break
            try:
                rotated_confidence = cls._ok_multiscale_confidence(
                    bgr,
                    template,
                    search_top_ratio=0.0,
                    search_bottom_ratio=1.0,
                    scales=cls._category_scan_scales(
                        f"icon_idle_rotated_{index}", rotated_full_scales
                    ),
                    normalized_width=cls.OK_ICON_NORMALIZED_WIDTH,
                    baseline_scale=1.0,
                    category_name=f"icon_idle_rotated_{index}",
                    hint_floor=cls.OK_IDLE_ROTATED_MATCH_THRESHOLD,
                )
            except (ValueError, cv2.error):
                continue
            if rotated_confidence > idle_confidence:
                idle_confidence = rotated_confidence
        if (
            idle_confidence >= cls.OK_IDLE_ROTATED_MATCH_THRESHOLD
            and idle_confidence - non_idle_confidence
            >= cls.OK_IDLE_ROTATED_MATCH_MARGIN
        ):
            cls._last_decided_state = IconState.IDLE_RECOVERY
            cls._note_icon_decision()
            return (
                IconState.IDLE_RECOVERY,
                idle_confidence,
                non_idle_confidence,
            )

        # 实机缩放会显著压低旋转整图模板分数。先要求整图轮廓与其他按钮拉开差距，
        # 再用固定在中心的黑点锚点校正；仍全部通过 OK FeatureSet 完成识别。
        if (
            idle_confidence >= cls.OK_IDLE_CORRECTED_MATCH_THRESHOLD
            and idle_confidence - non_idle_confidence
            >= cls.OK_IDLE_CORRECTED_MATCH_MARGIN
        ):
            center_template = cls._get_ok_idle_center_template()
            try:
                center_confidence = cls._ok_multiscale_confidence(
                    bgr,
                    center_template,
                    search_top_ratio=0.0,
                    search_bottom_ratio=1.0,
                    scales=np.linspace(0.55, 1.55, 21),
                    normalized_width=cls.OK_ICON_NORMALIZED_WIDTH,
                    baseline_scale=1.0,
                    category_name="icon_idle_center_anchor",
                    early_exit_confidence=cls.OK_IDLE_CENTER_MATCH_THRESHOLD,
                )
            except (ValueError, cv2.error):
                center_confidence = 0.0
            if center_confidence >= cls.OK_IDLE_CENTER_MATCH_THRESHOLD:
                cls._last_decided_state = IconState.IDLE_RECOVERY
                cls._note_icon_decision()
                return (
                    IconState.IDLE_RECOVERY,
                    max(idle_confidence, center_confidence),
                    non_idle_confidence,
                )
        cls._no_decision_streak += 1
        return None, max(best_confidence, idle_confidence), second_confidence
