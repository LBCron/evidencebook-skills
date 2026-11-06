// Draws the Studio page: reads a studio-view/v0 JSON on stdin, writes the page on stdout.
// The renderer is capsule-viewer's `studioViewDocument`; argv[2] is a capsule-viewer build
// (a directory holding dist/index.js) -- see studio_view.py and `terms studio --viewer`.
import { pathToFileURL } from "node:url";
import { join, resolve } from "node:path";
import { readFileSync } from "node:fs";

const viewer = resolve(process.argv[2]);
let studioViewDocument;
try {
  ({ studioViewDocument } = await import(pathToFileURL(join(viewer, "dist", "index.js")).href));
} catch (e) {
  console.error(`${viewer} could not be loaded: ${e instanceof Error ? e.message : e}`);
  process.exit(4);
}
if (typeof studioViewDocument !== "function") {
  console.error(`${viewer} has no studioViewDocument: it is a capsule-viewer older than the Studio page`);
  process.exit(3);
}
try {
  process.stdout.write(await studioViewDocument(JSON.parse(readFileSync(0, "utf8"))));
} catch (e) {
  console.error(e instanceof Error ? (e.reasons ? e.reasons.join("; ") : e.message) : String(e));
  process.exit(2);
}
