"""全部材料共用的队列流程：各种容量、跨轮次数、材料不足与补点边界。"""
from dataclasses import replace
from unittest import TestCase

from fishing_assistant.features.crafting.model import CraftOptions, CraftSession, CraftView, RECIPES


class CatalogFlowTests(TestCase):
    def simulate(self, recipe, capacity, count, exhaust=False):
        session = CraftSession(CraftOptions(recipe.key,'exhaust' if exhaust else 'count',count),0)
        slots = ('empty',)*capacity
        def overview():
            return CraftView(recipe.category,slots,(800,400),(170,700))
        view = overview()
        actions = []
        added = 0
        for now in range(1,400):
            decision = session.step(view,now)
            if session.finished:
                break
            if decision.action != 'wait':
                actions.append(decision.action)
            if decision.action == 'open_recipe':
                view = replace(overview(),dialog_open=True,dialog_recipe=recipe.key,process_point=(1500,900))
            elif decision.action == 'add':
                if exhaust and added == 2:
                    view = replace(view,insufficient=True)
                else:
                    index = slots.index('empty')
                    slots = slots[:index]+('busy',)+slots[index+1:]
                    added += 1
                    # 添加后保留详情，覆盖 Esc 返回再添加下一项的真实路径。
                    view = replace(view,slots=slots)
            elif decision.action == 'close_dialog':
                view = overview()
            elif decision.action == 'collect':
                self.assertTrue(all(x in ('empty','complete') for x in slots))
                view = CraftView(result=True)
            elif decision.action == 'confirm':
                slots = ('empty',)*capacity
                view = overview()
            elif session.phase == 'inspect' and not view.dialog_open:
                slots = tuple('complete' if x=='busy' else x for x in slots)
                view = overview()
        self.assertTrue(session.finished,(recipe.key,session.progress(now)))
        self.assertEqual(session.phase,'done',session.message)
        self.assertEqual((session.submitted,session.collected),(2,2) if exhaust else (count,count))
        self.assertEqual(actions.count('add'),3 if exhaust else count)
        self.assertEqual(actions.count('collect'),actions.count('confirm'))

    def test_all_materials_exact_count_across_queue_capacities_and_batches(self):
        for recipe in RECIPES:
            for capacity,count in ((1,1),(1,3),(4,6),(5,7),(8,9)):
                with self.subTest(recipe=recipe.key,capacity=capacity,count=count):
                    self.simulate(recipe,capacity,count)

    def test_all_materials_insufficient_drains_partial_queue_without_extra_add(self):
        for recipe in RECIPES:
            for capacity in (1,5):
                with self.subTest(recipe=recipe.key,capacity=capacity):
                    self.simulate(recipe,capacity,8,exhaust=True)

    def test_open_retry_is_bounded_and_never_becomes_space(self):
        session = CraftSession(CraftOptions(count=1),0)
        view = CraftView('wood',('empty',)*5,(800,400),(170,700))
        actions = []
        for now in range(1,30):
            decision = session.step(view,now)
            if decision.action != 'wait':
                actions.append(decision.action)
            if session.finished:
                break
        self.assertEqual(actions,['open_recipe','open_recipe'])
        self.assertEqual(session.phase,'error')
        self.assertIn('未打开详情',session.message)
        self.assertEqual(session.submitted,0)

    def test_open_retry_requires_same_known_queue_and_visible_recipe(self):
        original = CraftView('wood',('empty',)*5,(800,400),(170,700))
        for changed in (replace(original,recipe_point=None),replace(original,slots=('busy',)+('empty',)*4),
                        replace(original,slots=('unknown',)+('empty',)*4),replace(original,queue_complete=False)):
            session = CraftSession(CraftOptions(count=1),0)
            session.step(original,1)
            self.assertEqual(session.step(original,2).action,'open_recipe')
            for now in range(3,25):
                self.assertEqual(session.step(changed,now).action,'wait')
            self.assertEqual(session.submitted,0)
            self.assertEqual(session.phase,'error')

    def test_delayed_dialog_opens_before_retry_and_adds_only_once(self):
        session = CraftSession(CraftOptions(count=1),0)
        view = CraftView('wood',('empty',)*5,(800,400),(170,700))
        session.step(view,1)
        self.assertEqual(session.step(view,2).action,'open_recipe')
        self.assertEqual(session.step(view,3).action,'wait')
        view = replace(view,dialog_open=True,dialog_recipe='wood',process_point=(1500,900))
        session.step(view,4)
        self.assertEqual(session.step(view,5).action,'add')
        for now in range(6,25):
            self.assertEqual(session.step(view,now).action,'wait')
        self.assertEqual(session.phase,'error')
        self.assertIn('未确认队列增加',session.message)
        self.assertEqual(session.open_retry_count,0)

