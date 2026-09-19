import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fishing_assistant.config import AppConfig
from fishing_assistant.remote import CredentialStore, RemoteReporter, RemoteError, normalize_relay


class MemoryStore:
    def __init__(self, value=None): self.value=value or {}
    def load(self): return json.loads(json.dumps(self.value))
    def save(self, value): self.value=json.loads(json.dumps(value))


class RemoteTests(unittest.TestCase):
    def event(self, kind, **kwargs):
        return SimpleNamespace(kind=kind, message="", monitoring=False, icon_state="normal", **kwargs)

    def reporter(self, transport=None):
        store=MemoryStore(dict(relay="https://relay.example", write_token="a"*64, device_id="1"*36, enabled=True))
        return RemoteReporter(store, transport or Mock(return_value={"ok":True}))

    def test_disabled_by_default_and_no_network(self):
        transport=Mock()
        client=RemoteReporter(MemoryStore(),transport)
        self.assertFalse(client.report_once())
        transport.assert_not_called()

    def test_only_latest_status_and_one_report_per_minute(self):
        client=self.reporter()
        client.observe(SimpleNamespace(kind="metric",monitoring=True,icon_state="waiting_bite",message="PRIVATE CHAT"))
        client.sample(AppConfig(target_button_offset=(40,50)),True)
        self.assertTrue(client.report_once())
        self.assertFalse(client.report_once())
        payload=client.transport.call_args.args[3]
        self.assertEqual(payload["state"],"waiting_bite")
        self.assertTrue(payload["calibrated"])
        self.assertNotIn("PRIVATE",json.dumps(payload))
        self.assertNotIn("write_token",client.config())

    def test_network_failure_stays_outside_fishing_state(self):
        client=self.reporter(Mock(side_effect=OSError("SECRET")))
        client.sample(AppConfig(),False)
        self.assertTrue(client.report_once())
        self.assertIn("上报失败",client.connection_message)
        self.assertNotIn("SECRET",client.connection_message)
        self.assertFalse(client.snapshot["monitoring"])
        self.assertFalse(client.report_once())

    def test_pause_and_diagnostic_do_not_look_like_active_fishing(self):
        client=self.reporter()
        client.observe(SimpleNamespace(kind="state",monitoring=False,message="监测已暂停"))
        before=client.snapshot.copy()
        client.observe(SimpleNamespace(kind="diagnostic",message="诊断保存失败"))
        self.assertEqual(before,client.snapshot)
        self.assertEqual(client.snapshot["state"],"paused")
        client.sample(AppConfig(),False)
        self.assertFalse(client.snapshot["monitoring"])

    def test_engine_stall_detected_even_when_relay_is_online(self):
        client=self.reporter()
        client.last_observation=time.monotonic()-60
        client.sample(AppConfig(),True)
        self.assertEqual(client.snapshot["state"],"unresponsive")

    def test_stop_reason_is_allowlisted_not_raw_exception(self):
        client=self.reporter()
        client.observe(SimpleNamespace(kind="error",monitoring=False,message="背包已满 C:/private/secret"))
        self.assertEqual(client.snapshot["reason"],"inventory_full")
        self.assertNotIn("private",json.dumps(client.snapshot))

    def test_https_only_and_no_credentials_in_address(self):
        self.assertEqual(normalize_relay("https://relay.example/"),"https://relay.example")
        for value in ("http://relay.example","https://a:b@relay.example","https://relay.example/path",
                      "https://relay.example?token=secret","https://relay.example/#x"):
            with self.assertRaises(RemoteError): normalize_relay(value)

    def test_pending_activation_retry_retains_token_and_original_connection(self):
        client=self.reporter(Mock(side_effect=RemoteError("timeout")))
        original=client.config()
        for _ in range(2):
            with self.assertRaises(RemoteError): client.activate("https://other.example","B"*32,"custom")
        first,second=client.transport.call_args_list
        self.assertEqual(first.args[3]["write_token"],second.args[3]["write_token"])
        self.assertNotEqual(first.args[3]["write_token"],"a"*64)
        self.assertEqual(original,client.config())
        client.transport=Mock(return_value={"device_id":"b"*36})
        client.activate("https://other.example","B"*32,"custom")
        self.assertEqual(client.config()["relay"],"https://other.example")
        self.assertFalse(client.config()["enabled"])

    def test_shutdown_drops_late_network_result(self):
        client=self.reporter()
        client.transport=Mock(side_effect=lambda *args:client.close())
        client.report_once()
        self.assertNotIn("已上报",client.connection_message)
        self.assertFalse(client.report_once())

    def test_dpapi_persistence_is_encrypted_and_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=CredentialStore(Path(tmp)/"connection.bin")
            data=dict(relay="https://relay.example",write_token="a"*64,enabled=False)
            store.save(data)
            self.assertNotIn(b"relay.example",store.path.read_bytes())
            self.assertNotIn(b"a"*64,store.path.read_bytes())
            self.assertEqual(store.load(),data)
            store.path.write_bytes(b"invalid encrypted file")
            with self.assertRaises(RemoteError): store.load()

    def test_probe_does_not_send_a_credential(self):
        client=self.reporter(Mock(return_value={"protocol":1}))
        self.assertIn("连接正常",client.probe("https://relay.example"))
        self.assertEqual(client.transport.call_args.args,("https://relay.example","/v1/info"))
        client.transport=Mock(return_value={"protocol":2})
        with self.assertRaises(RemoteError): client.probe("https://relay.example")

    def test_reporter_detects_a_frozen_ui_without_another_sample(self):
        client=self.reporter()
        client.snapshot["monitoring"]=True
        client.snapshot["state"]="waiting_bite"
        client.last_observation=time.monotonic()-61
        client.report_once()
        self.assertEqual(client.transport.call_args.args[3]["state"],"unresponsive")

if __name__ == "__main__": unittest.main()
