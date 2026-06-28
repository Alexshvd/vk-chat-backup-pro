import { readFile, writeFile } from "node:fs/promises";
import { getPromptsBetweenCommitFilePath } from "./prompts-config.js";

export const AutoCommit = async ({ $, directory }) => {
  return {
    event: async ({ event }) => {
      if (event.type !== "session.idle") return;

      const status = await $`git status --porcelain`.text();
      if (!status.trim()) return;

      await $`git add -A`.quiet();

      const file = getPromptsBetweenCommitFilePath(directory);
      let body = "auto-commit";
      try {
        const content = await readFile(file, "utf-8");
        if (content.trim()) body = content.trim();
      } catch (e) { console.error("[auto-commit] Error reading prompts:", e); }

      await $`git commit -m "AiAgent auto-commit" -m ${body}`.quiet();
      await writeFile(file, "");
    },
  };
};
