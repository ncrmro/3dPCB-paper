// Polls the bambu-bridge sidecar's /print/status (slice + upload + start
// phases). The post-start live state comes from /api/printer/status.

import type { APIRoute } from "astro";
import { request as httpRequest } from "node:http";

export const prerender = false;

const SOCK = process.env.BAMBU_BRIDGE_SOCK;

export const GET: APIRoute = async () => {
  if (!SOCK) return jsonError(503, "bridge_not_configured", "BAMBU_BRIDGE_SOCK unset");
  return await new Promise<Response>((resolve) => {
    const req = httpRequest(
      { socketPath: SOCK, path: "/print/status", method: "GET", timeout: 2000 },
      (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (c: Buffer) => chunks.push(c));
        res.on("end", () => {
          resolve(
            new Response(Buffer.concat(chunks), {
              status: res.statusCode ?? 502,
              headers: {
                "content-type": res.headers["content-type"] ?? "application/json",
                "cache-control": "no-store",
              },
            }),
          );
        });
      },
    );
    req.on("error", (err: NodeJS.ErrnoException) => {
      const code = err.code === "ENOENT" ? "bridge_offline" : "bridge_unreachable";
      resolve(jsonError(503, code, err.message));
    });
    req.on("timeout", () => {
      req.destroy();
      resolve(jsonError(504, "bridge_timeout", "no reply in 2s"));
    });
    req.end();
  });
};

function jsonError(status: number, code: string, detail: string): Response {
  return new Response(JSON.stringify({ error: code, detail }), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}
