import assert from "node:assert/strict";
import test from "node:test";

import { codexThreadDeepLink, handleRequest } from "../src/index.mjs";

const THREAD_ID = "01a06b65-a6b1-7672-8959-961d8d130f66";

test("valid thread path opens only the corresponding Codex deep link", () => {
	assert.equal(
		codexThreadDeepLink(`/codex/open-thread/${THREAD_ID}`),
		`codex://threads/${THREAD_ID}`,
	);
});

test("thread IDs are canonicalized to lowercase", () => {
	assert.equal(
		codexThreadDeepLink(`/codex/open-thread/${THREAD_ID.toUpperCase()}/`),
		`codex://threads/${THREAD_ID}`,
	);
});

test("arbitrary redirects and malformed thread IDs are rejected", () => {
	for (const path of [
		"/",
		`/threads/${THREAD_ID}`,
		"/codex/open-thread/not-a-uuid",
		`/codex/open-thread/${THREAD_ID}/https://example.com`,
	]) {
		assert.equal(codexThreadDeepLink(path), null, path);
	}
});

test("valid bridge responses redirect and carry browser cache headers", () => {
	const response = handleRequest(
		new Request(`https://example.com/codex/open-thread/${THREAD_ID}`),
	);

	assert.equal(response.status, 302);
	assert.equal(response.headers.get("location"), `codex://threads/${THREAD_ID}`);
	assert.equal(
		response.headers.get("cache-control"),
		"public, max-age=86400, immutable",
	);
});

test("unsupported methods and invalid paths are rejected", () => {
	assert.equal(
		handleRequest(
			new Request(`https://example.com/codex/open-thread/${THREAD_ID}`, {
				method: "POST",
			}),
		).status,
		405,
	);
	assert.equal(handleRequest(new Request("https://example.com/nope")).status, 404);
});
