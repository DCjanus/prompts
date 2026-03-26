import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


def load_client_module():
    module_path = Path(__file__).resolve().parents[1] / "confluence_api_client.py"
    spec = importlib.util.spec_from_file_location("confluence_api_client", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load confluence_api_client module.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeHTTPXClient:
    def __init__(self, *args, **kwargs):
        self.calls = []
        self.kwargs = kwargs
        self._queue = []

    def queue(self, payload, status_code=200):
        self._queue.append(FakeResponse(payload, status_code=status_code))

    def _take(self):
        if not self._queue:
            raise AssertionError("No queued response")
        return self._queue.pop(0)

    def get(self, path, params=None):
        self.calls.append(("get", path, params, None, None))
        return self._take()

    def post(self, path, json=None, files=None, headers=None):
        self.calls.append(("post", path, None, json, {"files": files, "headers": headers}))
        return self._take()

    def put(self, path, json=None, params=None):
        self.calls.append(("put", path, params, json, None))
        return self._take()


class ConfluenceApiClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_client_module()

    def test_build_basic_auth_header(self):
        config = self.mod.ConfluenceConfig(
            base_url="https://example.com",
            username="user@example.com",
            token="secret",
        )
        headers = self.mod.ConfluenceApiClient._build_headers(config)
        self.assertIn("Authorization", headers)
        self.assertTrue(headers["Authorization"].startswith("Basic "))

    def test_update_page_uses_version_increment_and_representation(self):
        fake = FakeHTTPXClient()
        fake.queue({"id": "123", "version": {"number": 7}})
        fake.queue({"id": "123", "version": {"number": 8}})

        original_client = self.mod.httpx.Client
        self.mod.httpx.Client = lambda *args, **kwargs: fake
        try:
            client = self.mod.ConfluenceApiClient(
                self.mod.ConfluenceConfig(base_url="https://example.com", token="t")
            )
            result = client.update_page(
                page_id="123",
                title="T",
                body="<p>body</p>",
                representation="storage",
            )
        finally:
            self.mod.httpx.Client = original_client

        self.assertEqual(result["version"]["number"], 8)
        self.assertEqual(fake.calls[0][0], "get")
        self.assertEqual(fake.calls[1][0], "put")
        payload = fake.calls[1][3]
        self.assertEqual(payload["version"]["number"], 8)
        self.assertEqual(payload["body"]["storage"]["value"], "<p>body</p>")

    def test_attach_file_sets_no_check_header(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "a.txt"
            file_path.write_text("x", encoding="utf-8")

            fake = FakeHTTPXClient()
            fake.queue({"results": []})
            fake.queue({"results": [{"title": "a.txt"}]})

            original_client = self.mod.httpx.Client
            self.mod.httpx.Client = lambda *args, **kwargs: fake
            try:
                client = self.mod.ConfluenceApiClient(
                    self.mod.ConfluenceConfig(base_url="https://example.com", token="t")
                )
                client.attach_file("123", str(file_path))
            finally:
                self.mod.httpx.Client = original_client

        self.assertEqual(fake.calls[0][0], "get")
        method, path, _, _, extra = fake.calls[1]
        self.assertEqual(method, "post")
        self.assertEqual(path, "rest/api/content/123/child/attachment")
        self.assertEqual(extra["headers"]["X-Atlassian-Token"], "no-check")

    def test_attach_file_updates_existing_attachment_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "a.txt"
            file_path.write_text("x", encoding="utf-8")

            fake = FakeHTTPXClient()
            fake.queue({"results": [{"title": "a.txt", "id": "999"}]})
            fake.queue({"results": [{"title": "a.txt"}]})

            original_client = self.mod.httpx.Client
            self.mod.httpx.Client = lambda *args, **kwargs: fake
            try:
                client = self.mod.ConfluenceApiClient(
                    self.mod.ConfluenceConfig(base_url="https://example.com", token="t")
                )
                client.attach_file("123", str(file_path))
            finally:
                self.mod.httpx.Client = original_client

        self.assertEqual(fake.calls[1][1], "rest/api/content/123/child/attachment/999/data")


if __name__ == "__main__":
    unittest.main()
