// Dev-only endpoint that spawns the local CAD app to open a file.
//
// Why: the gallery's `Open in OpenSCAD / KiCad` action used to ship
// the file as a download, leaving the user's OS to launch the app.
// That works on a personal workstation with file associations set
// up, but feels disconnected. This endpoint instead asks the
// server (same machine that runs `bun run dev` + the cad/kicad
// nix shells) to launch the app directly with the source file.
//
// Security: only runs in dev mode (Astro static build has no
// server). Inputs are tightly validated: `tool` is whitelisted,
// `name` is a safe slug (no path traversal), and the resolved
// file must exist under the expected repo subdirectory. Treat
// this as `localhost`-only — it WILL spawn arbitrary local
// processes if exposed to the network.

import type { APIRoute } from "astro";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const prerender = false;

type Tool = "openscad" | "kicad";

interface ToolSpec {
  /** Directory containing the file to open. */
  dir: string;
  /** File extension (no dot). */
  ext: string;
  /** Nix flake directory to enter so the binary is on PATH. */
  nixDir: string;
  /** Executable name. */
  bin: string;
}

// Resolve repo root from this module's location:
// .../code/web/src/pages/api/open.ts → repo root is 5 levels up.
const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "..", "..", "..", "..", "..");

const TOOLS: Record<Tool, ToolSpec> = {
  openscad: {
    dir: resolve(REPO_ROOT, "code/cad/build"),
    ext: "scad",
    nixDir: resolve(REPO_ROOT, "code/cad"),
    bin: "openscad",
  },
  kicad: {
    dir: resolve(REPO_ROOT, "code/kicad"),
    ext: "kicad_pcb",
    nixDir: resolve(REPO_ROOT, "code/kicad"),
    bin: "kicad",
  },
};

const NAME_RE = /^[A-Za-z0-9_-]+$/;

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export const POST: APIRoute = async ({ request }) => {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return jsonResponse({ error: "invalid json body" }, 400);
  }
  const { tool, name } = (body ?? {}) as { tool?: string; name?: string };

  if (!tool || !(tool in TOOLS)) {
    return jsonResponse({ error: "tool must be one of " + Object.keys(TOOLS).join(",") }, 400);
  }
  if (!name || !NAME_RE.test(name)) {
    return jsonResponse({ error: "name must match " + NAME_RE.source }, 400);
  }

  const spec = TOOLS[tool as Tool];
  const filePath = resolve(spec.dir, `${name}.${spec.ext}`);
  // Belt-and-suspenders against directory traversal in case NAME_RE
  // ever loosens: resolved path must be a child of the allowed dir.
  if (!filePath.startsWith(spec.dir + "/")) {
    return jsonResponse({ error: "path outside tool dir" }, 400);
  }
  if (!existsSync(filePath)) {
    return jsonResponse({ error: "file not found", path: filePath }, 404);
  }

  // Spawn detached so the parent Astro request can return immediately
  // and the GUI app outlives the HTTP roundtrip. stdio is ignored so
  // a closed stream doesn't kill the child.
  const child = spawn(
    "nix",
    ["develop", spec.nixDir, "--command", spec.bin, filePath],
    { detached: true, stdio: "ignore" },
  );
  child.unref();

  return jsonResponse({ status: "launched", tool, file: filePath });
};
