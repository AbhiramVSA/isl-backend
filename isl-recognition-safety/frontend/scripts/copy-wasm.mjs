// Copies MediaPipe WASM runtime and the holistic landmarker model into public/.
// Idempotent; safe on Windows; never fails the install if a source is missing.
import { cpSync, existsSync, mkdirSync, readdirSync, copyFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");

function copyDir(src, dst) {
  if (!existsSync(src)) {
    console.log(`[copy-wasm] skip: ${src} not found`);
    return 0;
  }
  mkdirSync(dst, { recursive: true });
  let n = 0;
  for (const name of readdirSync(src)) {
    const s = join(src, name);
    const d = join(dst, name);
    if (statSync(s).isDirectory()) {
      cpSync(s, d, { recursive: true });
      n += 1;
    } else if (!existsSync(d) || statSync(d).size !== statSync(s).size) {
      copyFileSync(s, d);
      n += 1;
    }
  }
  return n;
}

const wasmSrc = join(root, "node_modules", "@mediapipe", "tasks-vision", "wasm");
const wasmDst = join(root, "public", "mediapipe-wasm");
console.log(`[copy-wasm] wasm: ${copyDir(wasmSrc, wasmDst)} file(s) copied to public/mediapipe-wasm`);

const modelSrc = resolve(root, "..", "models", "mediapipe", "holistic_landmarker.task");
const modelDst = join(root, "public", "models", "holistic_landmarker.task");
if (existsSync(modelSrc)) {
  mkdirSync(dirname(modelDst), { recursive: true });
  if (!existsSync(modelDst) || statSync(modelDst).size !== statSync(modelSrc).size) {
    copyFileSync(modelSrc, modelDst);
    console.log("[copy-wasm] model: copied holistic_landmarker.task");
  } else {
    console.log("[copy-wasm] model: up to date");
  }
} else {
  // Model absent: browser extraction will fall back to server-side frames.
}
