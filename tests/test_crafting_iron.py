"""用户铁锭截图回归及其余配方的合成详情验证；绝不连接真实游戏。"""
from dataclasses import replace
from pathlib import Path
import unittest
import cv2
import numpy as np

from fishing_assistant.constants import resource_path
from fishing_assistant.features.crafting.model import CraftOptions, CraftSession, RECIPES
from fishing_assistant.features.crafting.recognition import CraftVision

FIXTURES = Path(__file__).parent / 'fixtures'
ASSETS = resource_path('fishing_assistant','assets','crafting')


def fixture(name):
    image = cv2.imread(str(FIXTURES / ('crafting_iron_'+name+'.png')))
    assert image is not None
    return image


def paste(frame, key, x, y, factor=1):
    image = cv2.imread(str(ASSETS / (key+'.png')))
    assert image is not None
    if factor != 1:
        image = cv2.resize(image,None,fx=factor,fy=factor,interpolation=cv2.INTER_CUBIC)
    frame[y:y+image.shape[0],x:x+image.shape[1]] = image


class IronRecognitionTests(unittest.TestCase):
    def test_reported_overview_names_point_to_separate_cards(self):
        frame = fixture('overview')
        for factor in (.67,1,1.34,2):
            sample = cv2.resize(frame,None,fx=factor,fy=factor)
            for key,x in (('iron_ore',798),('iron_iron_ore',985)):
                with self.subTest(scale=factor,recipe=key):
                    view = CraftVision().inspect(sample,key)
                    self.assertEqual(view.slots,('empty',)*5)
                    self.assertFalse(view.dialog_open)
                    self.assertAlmostEqual(view.recipe_point[0],x*factor,delta=4)
                    self.assertAlmostEqual(view.recipe_point[1],402*factor,delta=4)

    def test_real_iron_detail_is_not_steel_and_requires_correct_ingredient(self):
        frame = fixture('detail')
        for factor in (.67,1,1.34,2):
            for selected in ('iron_ore','iron_iron_ore','steel'):
                with self.subTest(scale=factor,selected=selected):
                    view = CraftVision().inspect(cv2.resize(frame,None,fx=factor,fy=factor),selected)
                    self.assertTrue(view.dialog_open)
                    self.assertEqual(view.dialog_recipe,'iron_ore')
                    self.assertIsNotNone(view.process_point)
                    self.assertEqual(view.slots,('empty',)*5)

    def test_iron_ore_word_is_not_a_substring_confirmation(self):
        frame = fixture('detail')
        frame[708:760,1445:1540] = 25
        paste(frame,'ingredient_iron_ore',1460,721)
        view = CraftVision().inspect(frame,'iron_ore')
        self.assertEqual(view.dialog_recipe,'iron_iron_ore')

    def test_missing_or_ambiguous_ingredient_never_uses_selected_recipe(self):
        frame = fixture('detail')
        frame[708:760,1445:1540] = 25
        for selected in ('iron_ore','iron_iron_ore','steel'):
            self.assertEqual(CraftVision().inspect(frame,selected).dialog_recipe,'')
        paste(frame,'ingredient_ore',1360,721)
        paste(frame,'ingredient_iron_ore',1580,721)
        self.assertEqual(CraftVision().inspect(frame,'iron_ore').dialog_recipe,'')

    def test_blurred_iron_title_must_never_confirm_steel(self):
        for kernel in (3,5,7):
            for brightness in (.6,1):
                with self.subTest(blur=kernel,brightness=brightness):
                    frame = fixture('detail')
                    title = frame[345:400,1275:1390]
                    frame[345:400,1275:1390] = (cv2.GaussianBlur(title,(kernel,kernel),0)*brightness).astype(np.uint8)
                    view = CraftVision().inspect(frame,'steel')
                    self.assertIn(view.dialog_recipe,('iron_ore',''))

    def test_reproduced_images_reach_add_only_for_matching_recipe(self):
        vision = CraftVision()
        for selected in ('iron_ore','iron_iron_ore'):
            session = CraftSession(CraftOptions(recipe=selected,count=1),0)
            overview = vision.inspect(fixture('overview'),selected)
            session.step(overview,1)
            self.assertEqual(session.step(overview,2).action,'open_recipe')
            detail = vision.inspect(fixture('detail'),selected)
            session.step(detail,3)
            action = session.step(detail,4)
            self.assertEqual(action.action,'add' if selected=='iron_ore' else 'wait')
            if selected != 'iron_ore':
                self.assertTrue(session.finished)
            self.assertEqual(session.submitted,0)

    def test_all_other_recipe_titles_and_similar_names_in_synthetic_dialogs(self):
        for recipe in RECIPES:
            if recipe.key.startswith('iron_'):
                continue
            for factor in (1,1.6):
                with self.subTest(recipe=recipe.key,scale=factor):
                    frame = fixture('detail')
                    frame[:100,:270] = 25
                    paste(frame,'category_'+recipe.category,28,25)
                    frame[330:420,1260:1740] = 25
                    paste(frame,'recipe_'+recipe.key,1295,357,1.32)
                    view = CraftVision().inspect(cv2.resize(frame,None,fx=factor,fy=factor),recipe.key)
                    self.assertTrue(view.dialog_open)
                    self.assertEqual(view.dialog_recipe,recipe.key)


if __name__ == '__main__':
    unittest.main()
