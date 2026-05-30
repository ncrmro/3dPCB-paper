// Proxies the bambu-bridge sidecar's /status.json over a Unix domain
// socket. The bridge holds the printer's MQTT subscription + access
// code; this endpoint just forwards bytes so browser tabs never see
// printer credentials.
//
// SECURITY: socketPath is fs-permission gated (chmod 600 on the
// sidecar side). Astro processes running as the owning user can read
// it; nothing else on the box can.

import type { APIRoute } from "astro";
import { request } from "node:http";

export const prerender = false;

const SOCK = process.env.BAMBU_BRIDGE_SOCK;

export const GET: APIRoute = async () => {
  if (!SOCK) {
    return jsonError(503, "bridge_not_configured", "BAMBU_BRIDGE_SOCK unset");
  }
  return await new Promise<Response>((resolve) => {
    const req = request(
      { socketPath: SOCK, path: "/status.json", method: "GET", timeout: 2000 },
      (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (c: Buffer) => chunks.push(c));
        res.on("end", () => {
          resolve(
            new Response(Buffer.concat(chunks), {
              status: res.statusCode ?? 502,
              headers: {
                "content-type":
                  res.headers["content-type"] ?? "application/json",
                "cache-control": "no-store",
              },
            }),
          );
        });
        res.on("error", (err) =>
          resolve(jsonError(502, "bridge_read_error", err.message)),
        );
      },
    );
    req.on("error", (err: NodeJS.ErrnoException) => {
      // ENOENT = socket file missing → bridge isn't running.
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
    headers: {
      "content-type": "application/json",
      "cache-control": "no-store",
    },
  });
}
