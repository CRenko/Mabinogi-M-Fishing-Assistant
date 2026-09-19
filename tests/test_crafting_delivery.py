"""调用真实 OK 输入实现，但拦截全部 Win32 消息；不控制用户窗口。"""
from contextlib import nullcontext
from dataclasses import replace
from unittest import TestCase
from unittest.mock import Mock, patch
import numpy as np
import win32con

from fishing_assistant.automation.models import _OperationCancelled
from fishing_assistant.window_geometry import ClientFrame, ClientGeometry
from fishing_assistant.window_interaction import CheckedPostMessageInteraction
from fishing_assistant.window_target import OkWindowBackend, WindowInfo


class CraftDeliveryTests(TestCase):
    def setUp(self):
        self.info = WindowInfo(123,'game',10,20,1940,1040)
        self.g = ClientGeometry(123,'game',20,50,1920,1000,1940,1040,1)
        self.frame = ClientFrame(np.zeros((1000,1920,3),np.uint8),self.g)
        self.backend = OkWindowBackend(self.info)
        self.backend._capture = Mock()
        self.interaction = CheckedPostMessageInteraction(self.backend._capture,self.backend._adapter)
        self.backend._interaction = self.interaction
        self.active = True
        self.messages = []
        self.started = Mock()
        for name,value in (
            ('fishing_assistant.window_target.physical_window_coordinates',nullcontext),
            ('ok.device.interaction_methods.post_message.win32gui.ClientToScreen',lambda h,p:p),
            ('ok.device.interaction_methods.post_message.win32gui.ScreenToClient',lambda h,p:p),
            ('ok.device.interaction_methods.post_message.win32gui.IsWindow',lambda h:True),
        ):
            p = patch(name,side_effect=value)
            p.start(); self.addCleanup(p.stop)
        p = patch('fishing_assistant.window_target.read_client_geometry',side_effect=lambda *a:self.g)
        p.start(); self.addCleanup(p.stop)
        p = patch('fishing_assistant.window_interaction.win32gui.PostMessage',side_effect=self.post)
        self.send = p.start(); self.addCleanup(p.stop)
        p = patch('ok.device.interaction_methods.post_message.time.sleep')
        self.sleep = p.start(); self.addCleanup(p.stop)

    def post(self, hwnd, msg, w, l):
        self.messages.append((hwnd,msg,w,l))

    def check(self):
        if not self.active:
            raise _OperationCancelled()

    def click(self):
        self.backend.click_client(self.info,self.frame,(798,402),before_input=self.started,check_active=self.check)

    def test_native_ok_sequence_has_hover_and_hold_and_correct_coordinates(self):
        self.click()
        self.assertEqual([m[1] for m in self.messages],
            [win32con.WM_ACTIVATE,win32con.WM_MOUSEMOVE,win32con.WM_LBUTTONDOWN,win32con.WM_LBUTTONUP])
        self.assertTrue(all(m[0]==123 for m in self.messages))
        self.assertEqual(self.messages[-1][3],(402<<16)|798)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list],[.08,.08])
        self.started.assert_called_once()

    def test_pause_during_hover_prevents_down_and_leaves_decision_unsent(self):
        self.sleep.side_effect = lambda _: setattr(self,'active',False)
        with self.assertRaises(_OperationCancelled):
            self.click()
        self.assertNotIn(win32con.WM_LBUTTONDOWN,[m[1] for m in self.messages])
        self.started.assert_not_called()
        self.assertIsNone(self.interaction._client_guard)

    def test_resize_during_hover_prevents_down(self):
        self.sleep.side_effect = lambda _: setattr(self,'g',replace(self.g,dpi_scale=1.5))
        with self.assertRaisesRegex(RuntimeError,'已改变'):
            self.click()
        self.started.assert_not_called()
        self.assertNotIn(win32con.WM_LBUTTONDOWN,[m[1] for m in self.messages])

    def test_stop_during_hold_still_releases_mouse(self):
        def sleep(_):
            if any(m[1]==win32con.WM_LBUTTONDOWN for m in self.messages):
                self.active = False
        self.sleep.side_effect = sleep
        self.click()
        self.assertEqual(self.messages[-1][1],win32con.WM_LBUTTONUP)
        self.started.assert_called_once()

    def test_delivery_error_is_not_silently_reported_as_success(self):
        self.send.side_effect = OSError('access denied')
        with self.assertRaisesRegex(RuntimeError,'PostMessage 输入消息发送失败') as caught:
            self.click()
        self.assertIn('access denied', str(caught.exception))
        self.assertIn('消息 0x', str(caught.exception))
        self.assertIsInstance(caught.exception.__cause__, OSError)
        self.started.assert_not_called()
        self.assertIsNone(self.interaction._client_guard)

    def test_key_release_survives_stop_and_only_one_keydown_is_sent(self):
        self.sleep.side_effect = lambda _: setattr(self,'active',False)
        self.backend.tap_client_key(self.info,self.frame,'space',before_input=self.started,check_active=self.check)
        self.assertEqual([m[1] for m in self.messages],
            [win32con.WM_ACTIVATE,win32con.WM_KEYDOWN,win32con.WM_KEYUP])
        self.started.assert_called_once()
