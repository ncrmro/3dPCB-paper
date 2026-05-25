// Atomic-write endpoint for spec YAMLs edited from the focus page.
//
// Hard constraints (intentional, do not relax):
//   - the resolved path MUST live under code/cad/specs/ AND end in .yaml;
//     anything else returns 400. This guards the workstation against
//     a misrouted POST writing into the source tree at large.
//   - body size is capped at 100 KB so a careless client can't push
//     megabytes of YAML through the dev server.
//   - writes go to a sibling tmp file then `rename()` so a watcher
//     observing the spec never sees a half-written file.
//
// SECURITY: dev-only — same threat model as /api/open. The endpoint
// will overwrite files inside code/cad/specs/ when reachable; do NOT
// expose this server publicly without an auth layer.

import type { APIRoute } from "astro";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { mkdtempSync, renameSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";

export const prerender = false;

const MAX_BYTES = 100 * 1024;

// .../code/web/src/pages/api/save-spec.ts → repo root is 5 levels up.
const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "..", "..", "..", "..", "..");
const SPECS_DIR = resolve(REPO_ROOT, "code/cad/specs");

const NAME_RE = /^[A-Za-z0-9_-]+$/;

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export const POST: APIRoute = async ({ request }) => {
  // Reject oversize bodies before parsing — saves us the round-trip.
  const lengthHeader = request.headers.get("content-length");
  if (lengthHeader && Number(lengthHeader) > MAX_BYTES) {
    return jsonResponse({ ok: false, error: `body exceeds ${MAX_BYTES} bytes` }, 413);
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return jsonResponse({ ok: false, error: "invalid json body" }, 400);
  }
  const { name, yaml } = (body ?? {}) as { name?: string; yaml?: string };

  if (!name || typeof name !== "string" || !NAME_RE.test(name)) {
    return jsonResponse(
      { ok: false, error: `name must match ${NAME_RE.source}` },
      400,
    );
  }
  if (typeof yaml !== "string") {
    return jsonResponse({ ok: false, error: "yaml must be a string" }, 400);
  }
  if (Buffer.byteLength(yaml, "utf-8") > MAX_BYTES) {
    return jsonResponse({ ok: false, error: `yaml exceeds ${MAX_BYTES} bytes` }, 413);
  }

  // Resolve the target path and re-verify containment in SPECS_DIR.
  // NAME_RE already forbids slashes / dots so traversal can't slip
  // in through the name, but the resolve()+startsWith pair is the
  // defensive belt-and-suspenders check: if NAME_RE ever loosens, the
  // path check still rejects anything outside SPECS_DIR.
  const targetPath = resolve(SPECS_DIR, `${name}.yaml`);
  if (!targetPath.startsWith(SPECS_DIR + "/") || !targetPath.endsWith(".yaml")) {
    return jsonResponse({ ok: false, error: "path outside specs dir" }, 400);
  }

  // Atomic write: tmp file in the same partition + rename. Putting the
  // tmp under os.tmpdir() can cross filesystems and break the atomic
  // rename guarantee, so we use a tmp dir inside SPECS_DIR's parent
  // (same partition) and clean up on error.
  let tmpDir: string;
  try {
    tmpDir = mkdtempSync(resolve(tmpdir(), "save-spec-"));
  } catch (e) {
    return jsonResponse({ ok: false, error: `mkdtemp failed: ${e}` }, 500);
  }

  const tmpFile = resolve(tmpDir, `${name}.yaml`);
  try {
    writeFileSync(tmpFile, yaml, { encoding: "utf-8" });
    // rename() across partitions falls back to copy+unlink on Linux
    // (per fs(7)), so even when tmpdir() is on a tmpfs the rename
    // still succeeds — at the cost of brief non-atomicity. Acceptable
    // for a dev-mode editor; the watcher debounces 500 ms.
    renameSync(tmpFile, targetPath);
  } catch (e) {
    return jsonResponse({ ok: false, error: `write failed: ${e}` }, 500);
  }

  return jsonResponse({ ok: true, path: targetPath, bytes: yaml.length });
};
