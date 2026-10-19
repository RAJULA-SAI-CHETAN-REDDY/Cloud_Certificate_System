import { build } from "esbuild";
import { copyFile } from "node:fs/promises";

await build({ entryPoints: ["src/scan.js"], bundle: true, format: "iife", target: "es2022", outfile: "js/scan.js" });
await copyFile("node_modules/pdfjs-dist/build/pdf.worker.min.mjs", "js/pdf.worker.min.mjs");
