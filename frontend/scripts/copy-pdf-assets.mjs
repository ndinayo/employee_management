import { cpSync, mkdirSync, readFileSync } from "node:fs";

// Keep fonts and image decoders local, alongside the bundled PDF worker.
const source = new URL("../node_modules/pdfjs-dist/", import.meta.url);
const { version } = JSON.parse(readFileSync(new URL("package.json", source), "utf8"));
const target = new URL(`../public/pdfjs/${version}/`, import.meta.url);
mkdirSync(target, { recursive: true });
for (const directory of ["cmaps", "standard_fonts", "wasm", "iccs"]) {
  cpSync(new URL(directory, source), new URL(directory, target), { recursive: true });
}
cpSync(new URL("LICENSE", source), new URL("LICENSE", target));
