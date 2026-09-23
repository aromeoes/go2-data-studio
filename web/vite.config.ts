import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";
const source = (path: string) => fileURLToPath(new URL(path, import.meta.url));
export default defineConfig({
  resolve: {
    alias: [
      {
        find: "@dimos/sdk/internal/teleop",
        replacement: source(
          "../vendor/dimos-web/sdk/src/internal/teleopMachine.ts",
        ),
      },
      {
        find: "@dimos/sdk",
        replacement: source("../vendor/dimos-web/sdk/src/index.ts"),
      },
      {
        find: "@dimos/shared/manifest",
        replacement: source("../vendor/dimos-web/shared/manifest.ts"),
      },
      {
        find: "@dimos/shared",
        replacement: source("../vendor/dimos-web/shared/protocol.ts"),
      },
    ],
  },
});
