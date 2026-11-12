"""mnsv2 黑盒：复用常驻 Node worker（VM 只加载一次）产出 x3。

- MnsPool  : 维护 N 个常驻 node 进程（mns_worker.js），轮询派发，签名不再是进程级开销。
- MnsVM    : 进程内共享同一个 MnsPool（惰性创建），线程安全，可直接高并发调用。

如果每个请求的 bc/cookie/webSsk 不同（多账号），worker 会自动重建 VM；
同账号连续签名不会重建。多账号高并发建议每账号一个 pool（见 README）。
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import threading
from typing import Any, Dict, Optional


class MnsVMError(RuntimeError):
    pass


class _MnsWorker:
    """一个常驻 mns_worker.js 进程。"""

    def __init__(self, node: str, script: str) -> None:
        self.proc = subprocess.Popen(
            [node, script],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1,
        )
        self.lock = threading.Lock()

    def request(self, payload: Dict[str, Any]) -> str:
        with self.lock:
            if self.proc.poll() is not None:
                raise MnsVMError("mns_worker 已退出")
            try:
                self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, ValueError) as exc:
                raise MnsVMError(f"写入 worker 失败: {exc}") from exc
            line = self.proc.stdout.readline()
            if not line:
                raise MnsVMError("mns_worker 无响应")
            try:
                out = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MnsVMError(f"worker 返回非 JSON: {line[:200]}") from exc
            if "error" in out:
                raise MnsVMError(out["error"])
            return out["x3"]

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.terminate()
        except Exception:  # noqa: BLE001
            pass


class MnsPool:
    """N 个常驻 worker 的池，线程安全、轮询派发。"""

    def __init__(self, base_dir: Optional[str] = None, node: Optional[str] = None,
                 size: Optional[int] = None) -> None:
        base_dir = base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = os.path.join(base_dir, "mns_worker.js")
        if not os.path.exists(script):
            raise MnsVMError(f"找不到 {script}")
        node = node or os.environ.get("XHS_NODE") or shutil.which("node") or "node"
        if size is None:
            size = int(os.environ.get("XHS_MNS_WORKERS") or min(8, os.cpu_count() or 4))
        self.size = max(1, size)
        self._workers = [_MnsWorker(node, script) for _ in range(self.size)]
        self._idx = 0
        self._lock = threading.Lock()
        atexit.register(self.close)

    def sign(self, c: str, u: str, p: str, *, bc: str, cookie: str,
             web_ssk: Optional[str] = None, storage: Optional[Dict[str, str]] = None,
             app_id: str = "xhs-pc-web", ua: Optional[str] = None) -> str:
        payload: Dict[str, Any] = {"c": c, "u": u, "p": p, "bc": bc, "cookie": cookie, "appId": app_id}
        if web_ssk:
            payload["webSsk"] = web_ssk
        if storage:
            payload["storage"] = storage
        if ua:
            payload["ua"] = ua
        with self._lock:
            worker = self._workers[self._idx % self.size]
            self._idx += 1
        return worker.request(payload)

    def close(self) -> None:
        for w in self._workers:
            w.close()


# 进程内共享池（所有 XhsClient / 线程共用）
_POOL: Optional[MnsPool] = None
_POOL_LOCK = threading.Lock()


def get_pool(size: Optional[int] = None) -> MnsPool:
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = MnsPool(size=size)
    return _POOL


class MnsVM:
    """对外的 mnsv2 门面，内部走共享常驻池。"""

    def __init__(self, base_dir: Optional[str] = None, node: Optional[str] = None,
                 timeout: int = 60, pool_size: Optional[int] = None) -> None:
        # node 参数保留兼容；实际池由 get_pool 惰性创建
        self.pool = get_pool(pool_size)

    def sign(self, c: str, u: str, p: str, *, bc: str, cookie: str,
             web_ssk: Optional[str] = None, storage: Optional[Dict[str, str]] = None,
             app_id: str = "xhs-pc-web", ua: Optional[str] = None) -> str:
        return self.pool.sign(c, u, p, bc=bc, cookie=cookie, web_ssk=web_ssk,
                              storage=storage, app_id=app_id, ua=ua)
