"""Minimal single-worker SageMaker-compatible HTTP server for Model A."""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from src.model_a import run_model_a


MAX_BODY_BYTES = 4 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    def _write_json(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/ping":
            self._write_json(200, {"status": "ok"})
        else:
            self._write_json(404, {"error": "not_found"})

    def do_POST(self):
        if self.path != "/invocations":
            self._write_json(404, {"error": "not_found"})
            return
        if self.headers.get_content_type() != "application/json":
            self._write_json(415, {"error": "content_type_must_be_application_json"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY_BYTES:
                self._write_json(413, {"error": "invalid_payload_size"})
                return
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
            self._write_json(200, run_model_a(request))
        except Exception as error:
            self._write_json(400, {
                "error": type(error).__name__,
                "message": str(error),
            })

    def log_message(self, format_string, *args):
        print(json.dumps({
            "event": "HTTP_ACCESS",
            "client": self.client_address[0],
            "message": format_string % args,
        }))


def main():
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(json.dumps({"event": "MODEL_A_SERVER_READY", "port": port}))
    server.serve_forever()


if __name__ == "__main__":
    main()
