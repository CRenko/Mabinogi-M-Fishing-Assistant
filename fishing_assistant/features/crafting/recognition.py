"""OK FeatureSet 识别加工文字及可扩展队列，不匹配产物图案。"""
from __future__ import annotations

import cv2
import numpy as np
from collections import OrderedDict
from dataclasses import dataclass
from fishing_assistant.constants import resource_path
from fishing_assistant.features.crafting.model import CATEGORIES, CraftView, RECIPES, RECIPE_BY_KEY
from fishing_assistant.features.crafting.queue_recognition import inspect_queue
from ok.feature.FeatureSet import FeatureSet


@dataclass(frozen=True)
class Hit:
    x: int
    y: int
    width: int
    height: int
    score: float
    scale: float

    @property
    def center(self):
        return self.x + self.width // 2, self.y + self.height // 2


class CraftVision:
    # 只是匹配时的工作图基准，不是要求用户设置的分辨率。
    # inspect 按实际客户区等比归一化，所有点击位置通过 _point 还原到原帧。
    WIDTH = 1280
    HEIGHT = 720

    def __init__(self):
        self.feature_pool = OrderedDict()
        self.templates = {}
        self.resized = {}
        self.image = np.empty((0, 0, 3), np.uint8)
        self.ratio = 1.0

    def _template(self, key):
        if key not in self.templates:
            path = resource_path("fishing_assistant", "assets", "crafting", key + ".png")
            self.templates[key] = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if self.templates[key] is None:
                raise RuntimeError(f"缺少加工识别模板：{key}")
        return self.templates[key]

    def _match(self, key, area, *, threshold=0.84, scales=None, exact_word=False, ring_only=False, mask_function=None):
        height, width = self.image.shape[:2]
        x1, y1, x2, y2 = (round(v) for v in area)
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
        region = self.image[y1:y2, x1:x2]
        if not region.size:
            return None
        masked = key.endswith("_white")
        template = self._template(key.removesuffix("_white"))
        if masked:
            region = self._white_text(region)
            template = self._white_text(template)
        if ring_only:
            region = self._ring_edges(region)
        best = None
        for scale in scales or (0.50, 0.55, 0.60, 0.625, 0.65, 0.675, 0.70, 0.725, 0.75, 0.80, 0.85):
            cache_key = key, round(scale, 4), masked, ring_only
            if cache_key not in self.resized:
                self.resized[cache_key] = cv2.resize(template, (max(3, round(template.shape[1]*scale)),
                    max(3, round(template.shape[0]*scale))), interpolation=cv2.INTER_AREA)
                if ring_only:
                    self.resized[cache_key] = self._ring_edges(self.resized[cache_key])
            candidate = self.resized[cache_key]
            ch, cw = candidate.shape[:2]
            if ch > region.shape[0] or cw > region.shape[1]:
                continue
            shape = region.shape[:2]
            if shape not in self.feature_pool:
                self.feature_pool[shape] = FeatureSet(False, "__crafting_text_templates__.json",
                    default_horizontal_variance=0, default_vertical_variance=0, default_threshold=.84)
                if len(self.feature_pool) > 48:
                    self.feature_pool.popitem(last=False)
            self.feature_pool.move_to_end(shape)
            hits = self.feature_pool[shape].find_feature(region, "craft_"+key, template=candidate,
                       threshold=threshold, use_gray_scale=True, limit=6 if exact_word else 1,
                       mask_function=self._ring_mask if ring_only else mask_function)
            for box in hits:
                hit = Hit(round(x1+box.x), round(y1+box.y), cw, ch, float(box.confidence), scale)
                if exact_word and not self._word_boundary(hit):
                    continue
                if best is None or hit.score > best.score:
                    best = hit
        return best

    @staticmethod
    def _ring_edges(image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edge = cv2.Canny(gray, 60, 120)
        edge = cv2.dilate(edge, np.ones((3, 3), np.uint8))
        return cv2.cvtColor(edge, cv2.COLOR_GRAY2BGR)

    @staticmethod
    def _ring_mask(template):
        """只使用上半环及两侧边缘，排除中心材料图案和底部百分比文字。"""
        height, width = template.shape[:2]
        yy, xx = np.ogrid[:height, :width]
        radius = np.sqrt(((xx-(width-1)/2)/width)**2 + ((yy-(height-1)/2)/height)**2)
        return ((radius >= .39) & (radius <= .52) & (yy < height*.57)).astype(np.uint8)*255

    @staticmethod
    def _white_text(bgr):
        channels = bgr.astype(np.int16)
        mask = ((channels.min(axis=2) > 165) & (channels.max(axis=2)-channels.min(axis=2) < 65)).astype(np.uint8)*255
        return cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)

    def _word_boundary(self, hit):
        """排除 木材+、高级木材 中的 木材 子串，不能因名称前缀相同选错配方。"""
        gray = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)
        x, y, w, h = hit.x, hit.y, hit.width, hit.height
        core = gray[y:y+h, x:x+w]
        low, high = np.percentile(core, (15, 92))
        if high-low < 8:
            return False
        pad = max(2, round(5*hit.scale))
        yy1, yy2 = y+max(1, round(3*hit.scale)), y+h-max(1, round(3*hit.scale))
        for strip in (gray[yy1:yy2, max(0,x-pad):x], gray[yy1:yy2, x+w:x+w+pad]):
            if strip.size and np.count_nonzero(strip > low + (high-low)*0.65) > max(2, strip.size*.09):
                return False
        return True

    def _point(self, hit):
        return None if hit is None else tuple(round(v/self.ratio) for v in hit.center)

    def _dialog_recipe(self, category, heading, scale, scales):
        """详情标题按实际名称确认；铁锭的两种原料不能仅凭共同标题推断。"""
        h, w = self.image.shape[:2]
        title_area = (.63*w, .24*h, .97*w, .53*h)
        larger = tuple(round(scale*f, 4) for f in (1.18, 1.25, 1.32, 1.40, 1.48, 1.56))
        alternatives = [r.key for r in RECIPES if r.category == category
                        and r.key not in {"iron_ore", "iron_iron_ore"}]
        alternatives += {
            "wood": ["advanced_wood", "advanced_wood_plus"],
            "metal": ["alloy", "special_steel"],
            "cloth": ["advanced_cloth", "advanced_silk", "advanced_cloth_plus"],
            "leather": ["advanced_leather", "advanced_leather_plus"],
        }[category]
        candidates = []
        for key in alternatives:
            hit = self._match("recipe_"+key, title_area, threshold=.82, scales=larger, exact_word=True)
            if hit:
                candidates.append((hit.score, key))
        if category == "metal":
            iron = self._match("detail_iron", title_area, threshold=.86, scales=scales, exact_word=True)
            if iron:
                candidates.append((iron.score, "iron"))
        candidates.sort(reverse=True)
        if not candidates or (len(candidates) > 1 and candidates[0][0]-candidates[1][0] < .025):
            return ""
        key = candidates[0][1]
        if key != "iron":
            return key
        ingredients = []
        # 只查“所需材料”下方，不使用背景列表里包含括号的配方名。
        area = (.57*w, heading.y+heading.height, .98*w, .81*h)
        ingredient_scales = tuple(round(scale*f, 4) for f in (.85, .90, .94, .98, 1, 1.04, 1.10, 1.16))
        for template, recipe in (("ingredient_ore", "iron_ore"), ("ingredient_iron_ore", "iron_iron_ore")):
            hit = self._match(template, area, threshold=.86, scales=ingredient_scales, exact_word=True)
            if hit:
                ingredients.append(recipe)
        # 即便所选配方已知，也不能把模糊/缺失的原料名当作确认。
        return ingredients[0] if len(ingredients) == 1 else ""

    def inspect(self, frame: np.ndarray, recipe_key: str, *, queue_capacity: int = 0) -> CraftView:
        if frame.ndim != 3 or min(frame.shape[:2]) < 300:
            return CraftView(detail="画面尺寸过小")
        # 长宽比保留：超宽屏按高度保住文字大小，不能把整幅画面硬压到 1280 宽。
        self.ratio = max(self.WIDTH/frame.shape[1], self.HEIGHT/frame.shape[0])
        self.image = cv2.resize(frame[:, :, :3],
            (round(frame.shape[1]*self.ratio), round(frame.shape[0]*self.ratio)), interpolation=cv2.INTER_AREA)
        h, w = self.image.shape[:2]
        insufficient = self._match("insufficient", (.30*w, 0, .75*w, .20*h), threshold=.86)
        result = self._match("result", (.30*w, .14*h, .72*w, .40*h), threshold=.88)
        confirm = self._match("confirm", (.28*w, .80*h, .72*w, h), threshold=.86) if result else None
        if result and confirm:
            return CraftView(result=True, insufficient=bool(insufficient), detail=f"加工完成 {result.score:.2f}")

        titles = [(key, self._match("category_"+key, (0, 0, .25*w, .15*h), threshold=.86)) for key in CATEGORIES]
        titles = [(key, hit) for key, hit in titles if hit]
        if not titles:
            return CraftView(insufficient=bool(insufficient), detail="未匹配左上角加工标题")
        category, title = max(titles, key=lambda item: item[1].score)
        scale = title.scale
        scales = tuple(round(scale*factor, 4) for factor in (.94, .98, 1, 1.02, 1.06))
        collect = self._match("collect", (0, .38*h, .34*w, .91*h), threshold=.80, scales=scales)
        slots, queue_complete = inspect_queue(self, collect, scale, scales, queue_capacity)

        heading = self._match("detail_heading", (.55*w, .36*h, .95*w, .78*h), threshold=.83, scales=scales)
        recipe = RECIPE_BY_KEY[recipe_key]
        recipe_hit = None
        dialog_recipe = ""
        process = None
        if heading:
            dialog_recipe = self._dialog_recipe(category, heading, scale, scales)
            process = self._match("process", (.61*w, .79*h, .98*w, h), threshold=.82, scales=scales)
        elif category == recipe.category:
            # 配方列表相对左侧加工面板布局，不保证从屏幕宽度的 34% 开始。
            # OK 标题锚点与字号确定搜索下界；最终点击仍来自材料文字匹配。
            recipe_area = (min(.34*w, title.x+3*title.width),
                           min(.22*h, title.y+4*title.height),
                           .99*w, max(.57*h, title.y+12*title.height))
            recipe_hit = self._match("recipe_"+recipe_key, recipe_area,
                                      threshold=.84, scales=scales, exact_word=True)
        return CraftView(category, tuple(slots), self._point(recipe_hit), self._point(collect),
                         dialog_recipe, bool(heading), self._point(process), False, bool(insufficient),
                         f"{CATEGORIES[category]} {title.score:.2f}；队列 {len(slots)} 格：{' / '.join(slots)}",
                         queue_complete)
