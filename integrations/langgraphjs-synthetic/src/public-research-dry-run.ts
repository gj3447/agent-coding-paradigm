import { readFile } from "node:fs/promises";

import { canonicalJson } from "./pure.js";
import { compileRepositoryOwnedPublicResearchProjection } from "./public-research.js";

const manifestPath = process.argv.at(2);
if (manifestPath === undefined || process.argv.length !== 3) {
  throw new TypeError(
    "usage: public-research-dry-run.ts <projection-manifest.json>",
  );
}

const manifestText = await readFile(manifestPath, "utf8");
const manifest: unknown = JSON.parse(manifestText);
const { receipt } = compileRepositoryOwnedPublicResearchProjection(manifest);
process.stdout.write(`${canonicalJson(receipt)}\n`);
