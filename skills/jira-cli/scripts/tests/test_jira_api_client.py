from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import httpx2

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from jira_api_client import JiraApiClient, JiraApiError, JiraConfig  # noqa: E402


class JiraApiClientTest(unittest.TestCase):
    def make_client(self, handler):
        return JiraApiClient(
            JiraConfig(server="https://jira.example", token="secret"),
            transport=httpx2.MockTransport(handler),
        )

    def test_bearer_and_basic_auth_headers(self):
        bearer = JiraApiClient._build_headers(
            JiraConfig(server="https://jira.example", token="secret")
        )
        self.assertEqual(bearer["Authorization"], "Bearer secret")

        basic = JiraApiClient._build_headers(
            JiraConfig(
                server="https://jira.example",
                token="secret",
                username="jun",
                auth_type="basic",
            )
        )
        self.assertEqual(basic["Authorization"], "Basic anVuOnNlY3JldA==")

    def test_search_issues_preserves_query_contract(self):
        def handler(request: httpx2.Request) -> httpx2.Response:
            self.assertEqual(request.url.path, "/rest/api/2/search")
            self.assertEqual(request.url.params["jql"], "project = SATOS")
            self.assertEqual(request.url.params["fields"], "summary,status")
            self.assertEqual(request.url.params["startAt"], "10")
            return httpx2.Response(200, json={"issues": [], "total": 0})

        result = self.make_client(handler).search_issues(
            "project = SATOS",
            start_at=10,
            fields=["summary", "status"],
        )
        self.assertEqual(result["total"], 0)

    def test_create_metadata_uses_repeated_multi_value_parameters(self):
        def handler(request: httpx2.Request) -> httpx2.Response:
            self.assertEqual(
                request.url.params.get_list("projectKeys"), ["SATOS", "OTHER"]
            )
            self.assertEqual(
                request.url.params.get_list("issuetypeNames"), ["Task", "Bug"]
            )
            return httpx2.Response(200, json={"projects": []})

        self.make_client(handler).create_meta(
            project_keys=["SATOS", "OTHER"], issue_type_names=["Task", "Bug"]
        )

    def test_comment_body_is_sent_as_exact_jira_markup(self):
        expected = (
            "相关实现：[Midgard MR !38|https://git.example/midgard/merge_requests/38]"
        )

        def handler(request: httpx2.Request) -> httpx2.Response:
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.url.path, "/rest/api/2/issue/SATOS-1/comment")
            self.assertEqual(json.loads(request.content), {"body": expected})
            return httpx2.Response(201, json={"id": "123", "body": expected})

        result = self.make_client(handler).add_comment("SATOS-1", expected)
        self.assertEqual(result["body"], expected)

    def test_transition_resolves_exact_name_then_posts_id(self):
        requests: list[httpx2.Request] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            requests.append(request)
            if request.method == "GET":
                return httpx2.Response(
                    200,
                    json={
                        "transitions": [
                            {"id": "31", "name": "Mark as Done"},
                            {"id": "41", "name": "Cancel"},
                        ]
                    },
                )
            self.assertEqual(json.loads(request.content), {"transition": {"id": "31"}})
            return httpx2.Response(204)

        selected = self.make_client(handler).transition_issue("SATOS-1", "mark as done")
        self.assertEqual(selected["id"], "31")
        self.assertEqual([item.method for item in requests], ["GET", "POST"])

    def test_transition_accepts_fields_and_rejects_missing_required_values(self):
        requests: list[httpx2.Request] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            requests.append(request)
            if request.method == "GET":
                return httpx2.Response(
                    200,
                    json={
                        "transitions": [
                            {
                                "id": "31",
                                "name": "Resolve",
                                "fields": {
                                    "resolution": {"required": True},
                                    "environment": {
                                        "required": True,
                                        "hasDefaultValue": True,
                                    },
                                },
                            }
                        ]
                    },
                )
            self.assertEqual(
                json.loads(request.content),
                {
                    "transition": {"id": "31"},
                    "fields": {"resolution": {"name": "Done"}},
                },
            )
            return httpx2.Response(204)

        client = self.make_client(handler)
        with self.assertRaisesRegex(JiraApiError, "resolution"):
            client.transition_issue("SATOS-1", "Resolve")
        selected = client.transition_issue(
            "SATOS-1", "Resolve", fields={"resolution": {"name": "Done"}}
        )
        self.assertEqual(selected["id"], "31")
        self.assertEqual([item.method for item in requests], ["GET", "GET", "POST"])

    def test_unknown_transition_lists_available_values(self):
        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200, json={"transitions": [{"id": "31", "name": "Done"}]}
            )

        with self.assertRaisesRegex(JiraApiError, r"Done \(31\)"):
            self.make_client(handler).transition_issue("SATOS-1", "Missing")

    def test_delete_issue_sends_explicit_subtask_policy(self):
        def handler(request: httpx2.Request) -> httpx2.Response:
            self.assertEqual(request.method, "DELETE")
            self.assertEqual(request.url.params["deleteSubtasks"], "false")
            return httpx2.Response(204)

        self.make_client(handler).delete_issue("SATOS-1")

    def test_destructive_path_segments_are_rejected_before_request(self):
        requests: list[httpx2.Request] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            requests.append(request)
            return httpx2.Response(204)

        client = self.make_client(handler)
        for attachment_id in (
            "../issue/SATOS-1",
            "1/../../issue/SATOS-1",
            "1\\x",
            "123#ignored",
            "123?other=456",
            "%2e%2e%2fissue%2fSATOS-1",
        ):
            with (
                self.subTest(attachment_id=attachment_id),
                self.assertRaises(ValueError),
            ):
                client.delete_attachment(attachment_id)
        self.assertEqual(requests, [])

    def test_http_server_requires_explicit_dangerous_opt_in(self):
        with self.assertRaisesRegex(ValueError, "dangerously_allow_http"):
            JiraConfig(server="http://jira.example", token="secret")
        config = JiraConfig(
            server="http://jira.example",
            token="secret",
            dangerously_allow_http=True,
        )
        self.assertTrue(config.dangerously_allow_http)

    def test_transport_errors_are_converted_to_jira_api_errors(self):
        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("connection refused", request=request)

        with self.assertRaisesRegex(JiraApiError, "request failed") as raised:
            self.make_client(handler).server_info()
        self.assertIsNone(raised.exception.status_code)

    def test_attachment_uses_x_atlassian_token_header(self):
        def handler(request: httpx2.Request) -> httpx2.Response:
            self.assertEqual(request.headers["X-Atlassian-Token"], "no-check")
            self.assertIn("multipart/form-data", request.headers["Content-Type"])
            self.assertIn(b"hello", request.content)
            return httpx2.Response(200, json=[{"id": "99"}])

        with tempfile.TemporaryDirectory() as directory:
            file_path = Path(directory) / "hello.txt"
            file_path.write_text("hello", encoding="utf-8")
            result = self.make_client(handler).add_attachment("SATOS-1", file_path)
        self.assertEqual(result[0]["id"], "99")

    def test_api_get_rejects_absolute_and_non_rest_paths(self):
        client = self.make_client(lambda request: httpx2.Response(200, json={}))
        for path in (
            "https://evil.example/rest/api/2/myself",
            "plugins/servlet/x",
            "rest/api/2/../admin",
            "rest/%2e%2e/plugins/servlet/x",
            "rest/api/2/foo%2f..%2fadmin",
            "rest/api/2/search?jql=all",
            "rest/api/2/search#fragment",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                client.raw_get(path)

    def test_error_exposes_jira_payload_without_auth_header(self):
        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                400,
                json={
                    "errorMessages": ["Invalid issue"],
                    "errors": {"summary": "Required"},
                },
            )

        with self.assertRaises(JiraApiError) as raised:
            self.make_client(handler).get_issue("BAD-1")
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.payload["errors"]["summary"], "Required")
        self.assertNotIn("secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
