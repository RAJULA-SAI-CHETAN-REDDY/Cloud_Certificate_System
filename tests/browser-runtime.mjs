import { fileURLToPath } from "node:url";

export const root = fileURLToPath(new URL("../", import.meta.url));

export const python = process.env.CCD_TEST_PYTHON ||
  root + (process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");

export const browserOptions = process.platform === "win32" && !process.env.CI
  ? { channel: "msedge", headless: true }
  : { headless: true };
