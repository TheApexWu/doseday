import asyncio
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from models.cloud_pill_detector import (  # noqa: E402
    CloudPillDetector,
    _multipart_body,
    _unique_viam_detections,
)


UNIQUE_RESPONSE = {
    "ok": True,
    "result": {
        "count": 1,
        "candidate_count": 2,
        "match_status": "unique",
        "detections": [{
            "bbox": {
                "x_min": 453,
                "y_min": 333,
                "x_max": 590,
                "y_max": 462,
            },
            "confidence": 0.8123,
            "class_name": "pill",
            "shape": "round",
            "colors": [{"name": "white"}],
        }],
    },
}


class _DetectionHandler(BaseHTTPRequestHandler):
    request_body = b""
    content_type = ""

    def do_POST(self):
        type(self).content_type = self.headers["Content-Type"]
        type(self).request_body = self.rfile.read(
            int(self.headers["Content-Length"])
        )
        response = json.dumps(UNIQUE_RESPONSE).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format, *args):
        return


class CloudPillDetectorTests(unittest.TestCase):
    def test_unique_response_becomes_one_viam_detection(self):
        detections = _unique_viam_detections(
            UNIQUE_RESPONSE,
            "white",
            "round",
        )
        self.assertEqual(detections, [{
            "x_min": 453,
            "y_min": 333,
            "x_max": 590,
            "y_max": 462,
            "confidence": 0.8123,
            "class_name": "white-round",
        }])

    def test_ambiguous_response_returns_no_detection(self):
        payload = json.loads(json.dumps(UNIQUE_RESPONSE))
        payload["result"]["match_status"] = "ambiguous"
        payload["result"]["count"] = 2
        payload["result"]["detections"].append(
            payload["result"]["detections"][0]
        )
        self.assertEqual(
            _unique_viam_detections(payload, "white", "round"),
            [],
        )

    def test_multipart_body_contains_target_and_image(self):
        body, _ = _multipart_body(
            b"jpeg-bytes",
            "frame.jpg",
            "image/jpeg",
            "white",
            "round",
        )
        self.assertIn(b'name="target_color"', body)
        self.assertIn(b"white", body)
        self.assertIn(b'name="target_shape"', body)
        self.assertIn(b"round", body)
        self.assertIn(b'filename="frame.jpg"', body)
        self.assertIn(b"jpeg-bytes", body)

    def test_http_proxy_posts_expected_form(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _DetectionHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            proxy = SimpleNamespace(
                endpoint=(
                    f"http://127.0.0.1:{server.server_address[1]}/api/detect"
                ),
                request_timeout=2,
                api_token="",
            )
            payload = CloudPillDetector._post_detection(
                proxy,
                b"jpeg-data",
                "frame.jpg",
                "image/jpeg",
                "white",
                "round",
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertTrue(payload["ok"])
        self.assertIn("multipart/form-data", _DetectionHandler.content_type)
        self.assertIn(b"white", _DetectionHandler.request_body)
        self.assertIn(b"round", _DetectionHandler.request_body)
        self.assertIn(b"jpeg-data", _DetectionHandler.request_body)

    def test_target_commands_validate_and_clear(self):
        proxy = SimpleNamespace(target_color=None, target_shape=None)
        result = asyncio.run(CloudPillDetector.do_command(
            proxy,
            {
                "command": "set_target",
                "primary_color": "White",
                "shape": "Round",
            },
        ))
        self.assertEqual(result["primary_color"], "white")
        self.assertEqual(result["shape"], "round")

        cleared = asyncio.run(CloudPillDetector.do_command(
            proxy,
            {"command": "clear_target"},
        ))
        self.assertFalse(cleared["configured"])


if __name__ == "__main__":
    unittest.main()
