from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import run_same_session as runner


class FakeResponse:
    status_code = 200
    content = b"ok"
    headers = {"content-type": "application/json"}
    url = "https://www.adidas.com.hk/mock"


class FakeSession:
    class Cookies:
        @staticmethod
        def get_dict():
            return {}

    cookies = Cookies()

    @staticmethod
    def request(**kwargs):
        return FakeResponse()


server = runner.BrokerServer(("127.0.0.1", 0), FakeSession())
threading.Thread(target=server.serve_forever, daemon=True).start()
environment = os.environ.copy()
environment["ADIDAS_BROKER_PORT"] = str(server.server_address[1])
helper = Path(__file__).with_name("relay_helper.py")
process = subprocess.Popen(
    [sys.executable, str(helper)],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    env=environment,
)
request = {"id": 1, "method": "POST", "url": "https://www.adidas.com.hk/mock", "headers": [], "body": "e30="}
stdout, stderr = process.communicate(json.dumps(request) + "\n", timeout=5)
server.shutdown()
server.server_close()
response = json.loads(stdout)
assert response["status"] == 200, response
assert response["body"] == "b2s=", response
assert server.records[0]["request_body_length"] == 2, server.records
print({"status": response["status"], "relay_record_count": len(server.records), "offline_protocol": "pass"})
