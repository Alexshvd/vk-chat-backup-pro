import { appendFile } from "node:fs/promises";
import { getPromptsBetweenCommitFilePath } from "./prompts-config.js";

export const PromptLogger = async ({ directory }) => {
  const file = getPromptsBetweenCommitFilePath(directory);

  return {
    "chat.message": async (input, output) => {
      for (const part of output.parts) {
        if (part.type === "text" && part.text?.trim()) {
          try {
            await appendFile(file, `- ${part.text.trim()}\n`);
          } catch (e) { console.error("[prompt-logger] Ошибка записи:", e); }
        }
      }
    },
  };
};
