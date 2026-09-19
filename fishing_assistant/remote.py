"""Read-only remote status. Network errors never control the fishing engine."""
from __future__ import annotations
import ctypes
import hashlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from .constants import APP_VERSION

# Filled only after the maintainer deploys and verifies the official service.
OFFICIAL_RELAY_URL = ""
REMOTE_PATH = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MabinogiFishingHelper" / "remote" / "connection.bin"

class RemoteError(RuntimeError):
    pass

def normalize_relay(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path or len(value) > 240
            or any(c.isspace() for c in value)):
        raise RemoteError("请输入 HTTPS 中转地址，不含路径、账号或参数。")
    try:
        parsed.port
    except ValueError as error:
        raise RemoteError("中转端口不正确。") from error
    return value

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward credentials to a different origin.

def request_json(relay, path, method="GET", data=None, token=""):
    headers = {"Content-Type": "application/json", "User-Agent": f"ok-fishing/{APP_VERSION}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(normalize_relay(relay) + path,
                  data=None if data is None else json.dumps(data).encode("utf-8"), headers=headers, method=method)
    try:
        with build_opener(_NoRedirect).open(req, timeout=8) as response:
            payload = response.read(8193)
        if len(payload) > 8192:
            raise RemoteError("中转响应过大，请检查地址。")
        result = json.loads(payload)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except HTTPError as error:
        messages = {401: "设备授权已失效，请重新激活或联系中转管理员。",
                    403: "激活码无效、过期或已使用。", 409: "试验名额已满或激活码已使用。",
                    429: "操作过于频繁，请一分钟后再试。"}
        raise RemoteError(messages.get(error.code, f"中转暂不可用（HTTP {error.code}）。")) from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise RemoteError("无法连接中转，请检查网络和服务地址。") from None

def _crypt(data: bytes, *, decrypt=False) -> bytes:
    """Windows DPAPI, current user scope. No plaintext fallback."""
    if os.name != "nt":
        raise RemoteError("此设备尚不支持安全保存远程凭据。")
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, target = Blob(len(data), buffer), Blob()
    api = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    api.restype = wintypes.BOOL
    if not api(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise RemoteError("无法读取或保存设备凭据，请用原 Windows 账号重新配对。")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(target.data)

class CredentialStore:
    def __init__(self, path=REMOTE_PATH):
        self.path = path

    def load(self):
        if not self.path.exists():
            return {}
        try:
            raw = self.path.read_bytes()
            if len(raw) > 16384:
                raise ValueError
            data = json.loads(_crypt(raw, decrypt=True))
            normalize_relay(data["relay"])
            if not re.fullmatch(r"[a-f0-9]{64}", data.get("write_token", "")):
                raise ValueError
            data["enabled"] = data.get("enabled") is True and bool(data.get("device_id"))
            return data
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RemoteError):
            raise RemoteError("远程连接凭据不可用，请重新激活；本地钓鱼不受影响。") from None

    def save(self, data):
        encrypted = _crypt(json.dumps(data).encode("utf-8"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(encrypted)
        temporary.replace(self.path)

class RemoteReporter:
    INTERVAL = 60.0

    def __init__(self, store=None, transport=request_json):
        self.store, self.transport = store or CredentialStore(), transport
        self.lock, self.stop = threading.RLock(), threading.Event()
        self.thread = None
        self.generation = 0
        self.next_report = self.last_observation = 0.0
        self.connection_message = "远程查看已关闭"
        self.snapshot = dict(monitoring=False, calibrated=False, state="idle", strategy="stamina_bounce",
                             recognition="ok", reason="", version=APP_VERSION, observed_at=0)
        try:
            self.settings = self.store.load()
        except RemoteError as error:
            self.settings = {}
            self.connection_message = str(error)

    def config(self):
        with self.lock:
            return {k: v for k, v in self.settings.items() if k not in {"write_token", "pending"}}

    def _save(self, settings):
        self.store.save(settings)
        self.settings = settings
        self.generation += 1

    def activate(self, relay, code, source):
        relay = normalize_relay(relay)
        code = re.sub(r"[-\s]", "", code).upper()
        if not re.fullmatch(r"[A-F0-9]{32}", code):
            raise RemoteError("请输入完整的激活码。")
        fingerprint = hashlib.sha256(code.encode("ascii")).hexdigest()
        with self.lock:
            previous = self.settings.get("pending", {})
            token = previous.get("write_token") if previous.get("relay") == relay and previous.get("fingerprint") == fingerprint else None
            if self.settings.get("fingerprint") == fingerprint and self.settings.get("relay") == relay:
                token = self.settings.get("write_token")
            token = token or secrets.token_hex(32)
            pending = {"relay": relay, "write_token": token, "source": source, "enabled": False, "fingerprint": fingerprint}
            # Keep the working connection if a different activation fails. Retain the
            # pending token separately so a consumed code can survive a lost response.
            saved = self.settings.copy() if self.settings.get("device_id") else pending.copy()
            self._save({**saved, "pending": pending})
            generation = self.generation
        result = self.transport(relay, "/v1/activate", "POST", {"code": code, "write_token": token})
        if not re.fullmatch(r"[a-f0-9-]{36}", str(result.get("device_id", ""))):
            raise RemoteError("中转返回的设备信息不正确。")
        with self.lock:
            if self.stop.is_set() or generation != self.generation:
                raise RemoteError("连接设置已改变，请重试。")
            self._save({**pending, "device_id": result["device_id"]})
            self.connection_message = "激活成功，打开远程查看后可上报状态"
        return result["device_id"]

    def set_enabled(self, enabled):
        with self.lock:
            if not self.settings.get("device_id"):
                raise RemoteError("请先激活中转服务。")
            self._save({**self.settings, "enabled": bool(enabled)})
            self.connection_message = "等待首次上报" if enabled else "远程查看已关闭；手机将显示最后收到的状态"

    def pair(self):
        with self.lock:
            settings, generation = self.settings.copy(), self.generation
        if not settings.get("device_id"):
            raise RemoteError("请先激活中转服务。")
        result = self.transport(settings["relay"], "/v1/pair", "POST", {}, settings["write_token"])
        if not re.fullmatch(r"[a-f0-9]{48}", str(result.get("pair_code", ""))):
            raise RemoteError("中转返回的配对信息不正确。")
        with self.lock:
            if generation != self.generation or self.stop.is_set():
                raise RemoteError("连接设置已改变，请重新生成二维码。")
        query = urlencode({"v": "1", "relay": settings["relay"], "code": result["pair_code"]})
        return "okfishing://pair?" + query, int(result["expires_at"])

    def unpair(self):
        with self.lock:
            settings = self.settings.copy()
        if not settings.get("device_id"):
            raise RemoteError("尚未激活。")
        self.transport(settings["relay"], "/v1/unpair", "POST", {}, settings["write_token"])

    def probe(self, relay):
        started = time.monotonic()
        result = self.transport(normalize_relay(relay), "/v1/info")
        if result.get("protocol") != 1:
            raise RemoteError("地址可访问，但不是兼容的远程中转。")
        return f"中转连接正常 · {round((time.monotonic() - started) * 1000)} ms（仅代表当前网络）"

    def observe(self, event):
        kind = getattr(event.kind, "value", event.kind)
        if kind not in {"metric", "state", "error", "warning"}:
            return
        with self.lock:
            self.last_observation = time.monotonic()
            self.snapshot["observed_at"] = int(time.time())
            if kind == "metric" and event.monitoring:
                icon = getattr(event.icon_state, "value", event.icon_state)
                self.snapshot["state"] = icon if icon in {"waiting_bite", "ready_to_cast", "fish_hooked", "idle_recovery"} else "running"
            elif kind == "state":
                self.snapshot["state"] = "running" if event.monitoring else "paused"
                if event.monitoring and ("清理背包" in event.message or "背包清理" in event.message):
                    self.snapshot["state"] = "cleaning"
                self.snapshot["reason"] = "" if event.monitoring else "manual"
            elif kind == "error" and not event.monitoring:
                self.snapshot["state"] = "stopped"
                self.snapshot["reason"] = next((value for word, value in (
                    ("背包", "inventory_full"), ("鱼竿", "rod_required"), ("钓竿", "rod_required"),
                    ("重试", "retry_limit"), ("恢复", "retry_limit")) if word in event.message), "error")

    def sample(self, config, monitoring):
        with self.lock:
            self.snapshot.update(monitoring=monitoring,
                calibrated=bool(config.target_button_offset if config.capture_mode == "window" else config.button_center),
                strategy=config.catch_strategy, recognition=config.recognition_backend)
            if monitoring and time.monotonic() - self.last_observation > 30:
                self.snapshot["state"] = "unresponsive"
            elif not monitoring and self.snapshot["state"] not in {"idle", "paused", "stopped"}:
                self.snapshot["state"] = "paused"

    def report_once(self):
        with self.lock:
            if self.stop.is_set() or not self.settings.get("enabled") or time.monotonic() < self.next_report:
                return False
            settings, payload, generation = self.settings.copy(), self.snapshot.copy(), self.generation
            if payload["monitoring"] and time.monotonic() - self.last_observation > 30:
                payload["state"] = "unresponsive"
            self.next_report = time.monotonic() + self.INTERVAL
        try:
            result = self.transport(settings["relay"], "/v1/status", "PUT", payload, settings["write_token"])
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise RemoteError("中转没有确认收到状态。")
            message = "已上报 · " + time.strftime("%H:%M:%S")
        except Exception:
            message = "上报失败，一分钟后重试；本地钓鱼不受影响"
        with self.lock:
            if generation == self.generation and not self.stop.is_set():
                self.connection_message = message
        return True

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name="remote-status", daemon=True)
            self.thread.start()

    def _run(self):
        while not self.stop.wait(1):
            self.report_once()

    def close(self):
        self.stop.set()
        with self.lock:
            self.generation += 1
        if self.thread is not None:
            self.thread.join(timeout=0.1)
