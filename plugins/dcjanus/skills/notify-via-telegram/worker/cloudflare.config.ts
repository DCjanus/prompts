import { defineConfig } from "cf/config";

export default defineConfig({
	worker: {
		name: "codex-thread-bridge",
		compatibilityDate: "2026-09-04",
		entrypoint: "src/index.mjs",
		workersDev: true,
		previewUrls: false,
		observability: {
			enabled: true,
		},
	},
});
