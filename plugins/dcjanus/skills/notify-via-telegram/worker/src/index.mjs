const THREAD_PATH_PATTERN =
	/^\/codex\/open-thread\/([0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\/?$/i;

export function codexThreadDeepLink(pathname) {
	const match = pathname.match(THREAD_PATH_PATTERN);
	return match ? `codex://threads/${match[1].toLowerCase()}` : null;
}

export function handleRequest(request) {
	if (request.method !== "GET" && request.method !== "HEAD") {
		return new Response("Method Not Allowed", {
			status: 405,
			headers: { Allow: "GET, HEAD" },
		});
	}

	const deepLink = codexThreadDeepLink(new URL(request.url).pathname);
	if (!deepLink) {
		return new Response("Not Found", { status: 404 });
	}

	return new Response(null, {
		status: 302,
		headers: {
			"Cache-Control": "public, max-age=86400, immutable",
			Location: deepLink,
			"Referrer-Policy": "no-referrer",
			"X-Content-Type-Options": "nosniff",
		},
	});
}

export default {
	fetch(request) {
		return handleRequest(request);
	},
};
