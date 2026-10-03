import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agp9_ready import comment


class Fake(BaseHTTPRequestHandler):
    comments: list = []
    deny = False
    log: list = []

    def _send(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

    def do_GET(self):
        Fake.log.append(("GET", self.path, self.headers.get("Authorization")))
        self._send(403 if Fake.deny else 200, {} if Fake.deny else Fake.comments)

    def do_POST(self):
        Fake.log.append(("POST", self.path, None))
        c = {"id": len(Fake.comments) + 1, "body": self._body()["body"]}
        Fake.comments.append(c)
        self._send(201, c)

    def do_PATCH(self):
        Fake.log.append(("PATCH", self.path, None))
        cid = int(self.path.rsplit("/", 1)[1])
        for c in Fake.comments:
            if c["id"] == cid:
                c["body"] = self._body()["body"]
        self._send(200, {})

    def log_message(self, *a):
        pass


@pytest.fixture
def api():
    Fake.comments, Fake.deny, Fake.log = [{"id": 99, "body": "someone else's comment"}], False, []
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_create_then_update_then_unchanged(api):
    assert comment.upsert(api, "tok", "o/r", 7, "## one")[0] == "created"
    assert comment.upsert(api, "tok", "o/r", 7, "## one")[0] == "unchanged"
    assert comment.upsert(api, "tok", "o/r", 7, "## two")[0] == "updated"
    mine = [c for c in Fake.comments if c["body"].startswith(comment.MARKER)]
    assert len(mine) == 1 and "## two" in mine[0]["body"]
    assert Fake.comments[0]["body"] == "someone else's comment"
    assert Fake.log[0][2] == "Bearer tok"


def test_permission_denied_is_a_skip_not_a_failure(api):
    Fake.deny = True
    action, info = comment.upsert(api, "tok", "o/r", 7, "x")
    assert action == "skipped" and "pull-requests: write" in info


def test_eligibility():
    ev = {"pull_request": {"number": 3, "head": {"repo": {"full_name": "O/R"}}}}
    assert comment.eligibility(ev, "o/r") == ("ok", 3)
    assert comment.eligibility({"pull_request": {"number": 3, "head": {"repo": {"full_name": "fork/r"}}}}, "o/r")[0] == "skip"
    assert comment.eligibility({"pull_request": {"number": 3, "head": {"repo": None}}}, "o/r")[0] == "skip"
    assert comment.eligibility({"push": {}}, "o/r")[0] == "skip"


def test_body_is_truncated_and_marked():
    body = comment.build_body("x" * 70000)
    assert body.startswith(comment.MARKER) and len(body) < 65536


def test_main_end_to_end(api, tmp_path):
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps({"pull_request": {"number": 5, "head": {"repo": {"full_name": "o/r"}}}}))
    md = tmp_path / "r.md"
    md.write_text("## agp9-ready\nNo new findings.\n")
    out = []
    env = {"GITHUB_REPOSITORY": "o/r", "GITHUB_TOKEN": "tok", "GITHUB_EVENT_PATH": str(ev), "GITHUB_API_URL": api}
    assert comment.main([str(md)], env, out.append) == 0
    assert comment.main([str(md)], env, out.append) == 0
    assert "created" in out[0] and "unchanged" in out[1]
    assert comment.main([str(md)], {}, out.append) == 0 and "no sticky comment" in out[-1]
