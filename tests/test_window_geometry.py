"""客户区坐标、OK 裁边与 DPI 回归；不向真实窗口发送输入。"""
from contextlib import contextmanager, nullcontext
import ctypes
from dataclasses import replace
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import numpy as np

from fishing_assistant.window_geometry import ClientFrame, ClientGeometry, physical_window_coordinates, read_client_geometry
from fishing_assistant.window_target import OkWindowBackend, WindowInfo


class GeometryFixtures:
    def geometry(self, width=1920, height=1000, dpi=1.0):
        return ClientGeometry(123, "game", -1700, 30, width, height, width+20, height+40, dpi)

    def snapshot(self, geometry=None):
        g = geometry or self.geometry()
        return ClientFrame(np.zeros((g.height, g.width, 3), np.uint8), g)


class ClientGeometryTests(GeometryFixtures, TestCase):
    def test_any_client_resolution_and_dpi_use_the_same_pixel_contract(self):
        for width, height in ((853, 517), (1366,768), (1920,1000), (2560,1600), (3440,1440), (3840,2160)):
            for dpi in (1,1.25,1.5,2):
                with self.subTest(size=(width,height), dpi=dpi):
                    frame = self.snapshot(self.geometry(width,height,dpi))
                    for point in ((0,0), (width-1,height-1), (width//3,height//3)):
                        self.assertEqual(frame.client_point(point), point)
                    self.assertEqual(frame.client_point(None), (width//2,height//2))

    def test_stale_cropped_frame_is_not_blindly_stretched(self):
        snapshot = self.snapshot()
        for image in (snapshot.image[:-20], snapshot.image[:, :-20], np.zeros((500,960,3), np.uint8)):
            with self.assertRaisesRegex(RuntimeError, "尚未同步"):
                ClientFrame(image, snapshot.geometry).client_point((100,100))

    def test_invalid_coordinates_are_rejected_not_clamped_to_a_button(self):
        snapshot = self.snapshot()
        for point in ((-1,0), (1920,10), (10,1000), (float("nan"),1), (1,float("inf"))):
            with self.subTest(point=point), self.assertRaisesRegex(RuntimeError, "超出"):
                snapshot.client_point(point)

    def test_move_is_safe_but_dpi_size_or_target_change_needs_new_capture(self):
        snapshot = self.snapshot()
        snapshot.ensure_current(replace(snapshot.geometry, left=300, top=500))
        for changes in ({"width":1280}, {"dpi_scale":1.5}, {"handle":456}, {"title":"other"}, {"window_height":1080}):
            with self.subTest(changes=changes), self.assertRaisesRegex(RuntimeError, "已改变"):
                snapshot.ensure_current(replace(snapshot.geometry, **changes))

    def test_dpi_context_is_restored_even_after_failure(self):
        setter = Mock(return_value=111)
        with patch("fishing_assistant.window_geometry.ctypes.WinDLL", return_value=SimpleNamespace(SetThreadDpiAwarenessContext=setter)):
            with self.assertRaisesRegex(ValueError, "test"):
                with physical_window_coordinates():
                    self.assertEqual(ctypes.c_ssize_t(setter.call_args.args[0].value).value, -4)
                    raise ValueError("test")
        self.assertEqual(setter.call_args.args[0], 111)

    def test_geometry_provider_uses_ok_client_bounds_not_outer_size(self):
        with patch("win32gui.IsWindow", return_value=True), patch("win32gui.IsWindowVisible", return_value=True), \
             patch("win32gui.IsIconic", return_value=False), patch("win32gui.GetWindowText", return_value="game"), \
             patch("ok.util.window.get_window_bounds", return_value=(-1700,30,1940,1040,1920,1000,1.25)) as bounds:
            self.assertEqual(read_client_geometry(123,"game"), self.geometry(dpi=1.25))
        bounds.assert_called_once_with(123)


class OkClientBackendTests(GeometryFixtures, TestCase):
    def setUp(self):
        self.info = WindowInfo(123,"game",-1710,0,1940,1040)
        self.backend = OkWindowBackend(self.info)
        self.backend._capture = Mock()
        self.backend._interaction = Mock()
        @contextmanager
        def guard(check_active, before_input):
            check_active()
            before_input()
            yield
        self.backend._interaction.input_guard.side_effect = guard
        self.g = self.geometry()
        self.context = patch("fishing_assistant.window_target.physical_window_coordinates", side_effect=nullcontext)
        self.context.start()
        self.addCleanup(self.context.stop)
        self.bounds = patch("fishing_assistant.window_target.read_client_geometry", return_value=self.g)
        self.read_geometry = self.bounds.start()
        self.addCleanup(self.bounds.stop)

    def test_ok_itself_crops_title_and_border_using_actual_client_size(self):
        from ok.device.capture_methods.windows_graphics import WindowsGraphicsCaptureMethod
        raw = np.zeros((1040,1940,3), np.uint8)
        raw[30,10] = (1,2,3)
        # 调用安装版 OK 的真正裁剪函数，不能只让 Mock 返回期望尺寸。
        capture = SimpleNamespace(hwnd_window=self.backend._adapter)
        self.backend._capture.get_frame.side_effect = lambda: WindowsGraphicsCaptureMethod.crop_image(capture, raw)
        frame = self.backend.capture_client_frame(self.info)
        self.assertEqual(frame.image.shape, (1000,1920,3))
        np.testing.assert_array_equal(frame.image[0,0], (1,2,3))
        self.assertEqual((self.backend._adapter.x,self.backend._adapter.y), (-1700,30))
        self.assertEqual((self.backend._adapter.window_width,self.backend._adapter.width), (1940,1920))

    def test_click_hover_and_key_use_client_coordinates_and_recheck_before_input(self):
        frame = self.snapshot(self.g)
        check = Mock()
        active = Mock()
        self.backend.click_client(self.info,frame,(800,400),before_input=check,check_active=active)
        self.backend.hover_client(self.info,frame,(1200,800),before_input=Mock())
        self.backend.tap_client_key(self.info,frame,"space",before_input=check,check_active=active)
        self.backend._interaction.click.assert_called_once_with(800,400,down_time=0.08)
        self.backend._interaction.move.assert_called_once_with(1200,800)
        self.backend._interaction.send_key.assert_called_once_with("space",0.08)
        self.assertEqual(check.call_count,2)
        self.assertEqual(self.read_geometry.call_count,6)

    def test_ok_crop_and_click_with_logical_outer_bounds_and_physical_client(self):
        from ok.device.capture_methods.windows_graphics import WindowsGraphicsCaptureMethod
        for width,height,dpi,frameless in ((1366,768,1.25,False), (2560,1600,1.5,False),
                                         (3440,1440,1.5,True), (3840,2160,2,False)):
            with self.subTest(size=(width,height),dpi=dpi,frameless=frameless):
                border = 0 if frameless else round(10*dpi)
                title = 0 if frameless else round(30*dpi)
                ww,wh = width+2*border,height+border+title
                geometry = replace(self.g,width=width,height=height,window_width=ww,window_height=wh,dpi_scale=dpi)
                info = replace(self.info,width=round(ww/dpi),height=round(wh/dpi))
                self.read_geometry.return_value = geometry
                raw = np.zeros((wh,ww,3),np.uint8)
                raw[title,border] = (10,20,30)
                capture = SimpleNamespace(hwnd_window=self.backend._adapter)
                self.backend._capture.get_frame.side_effect = lambda: WindowsGraphicsCaptureMethod.crop_image(capture,raw)
                frame = self.backend.capture_client_frame(info)
                self.assertEqual(frame.image.shape, (height,width,3))
                np.testing.assert_array_equal(frame.image[0,0], (10,20,30))
                point = (width//2,height//2)
                self.backend.click_client(info,frame,point,before_input=Mock())
                self.backend._interaction.click.assert_called_with(*point,down_time=0.08)

    def test_missing_click_target_is_not_replaced_with_window_center(self):
        with self.assertRaisesRegex(RuntimeError,"未找到"):
            self.backend.click_client(self.info,self.snapshot(),None,before_input=Mock())
        self.backend._interaction.click.assert_not_called()

    def test_geometry_change_during_capture_discards_frame(self):
        self.backend._capture.get_frame.return_value = self.snapshot().image
        self.read_geometry.side_effect = [self.g,replace(self.g,dpi_scale=1.5)]
        with self.assertRaisesRegex(RuntimeError,"已改变"):
            self.backend.capture_client_frame(self.info)
        self.backend._interaction.click.assert_not_called()

    def test_change_between_hover_and_space_sends_no_key(self):
        frame = self.snapshot()
        self.backend.hover_client(self.info,frame,(800,400),before_input=Mock())
        self.read_geometry.return_value = replace(self.g,width=1280)
        with self.assertRaisesRegex(RuntimeError,"已改变"):
            self.backend.tap_client_key(self.info,frame,"space",before_input=Mock())
        self.backend._interaction.send_key.assert_not_called()

    def test_stop_after_geometry_query_sends_no_input(self):
        def stop():
            raise RuntimeError("cancelled")
        with self.assertRaisesRegex(RuntimeError,"cancelled"):
            self.backend.click_client(self.info,self.snapshot(),(800,400),before_input=stop)
        self.backend._interaction.click.assert_not_called()

    def test_legacy_fishing_path_restores_old_calibration_coordinates(self):
        frame = self.snapshot()
        self.backend.click_client(self.info,frame,(800,400),before_input=Mock())
        signature = self.backend._adapter.capture_target_signature
        self.backend.keep_hover(self.info,(1800,900))
        self.backend._interaction.move.assert_called_once_with(1800,900)
        self.assertEqual(self.backend._adapter.width,1940)
        self.assertNotEqual(self.backend._adapter.capture_target_signature,signature)
