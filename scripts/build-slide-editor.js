/**
 * Bundle iframe slide-editor runtime → public/slide-editor/runtime.js
 */
const esbuild = require("esbuild");
const path = require("path");

const root = path.join(__dirname, "..");

esbuild
  .build({
    entryPoints: [path.join(root, "frontend/src/slide-editor/runtime/index.ts")],
    bundle: true,
    outfile: path.join(root, "frontend/public/slide-editor/runtime.js"),
    format: "iife",
    platform: "browser",
    target: ["es2019"],
    sourcemap: false,
    minify: true,
    logLevel: "info",
  })
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
