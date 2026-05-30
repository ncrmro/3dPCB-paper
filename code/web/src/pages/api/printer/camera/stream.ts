// Streams the bridge's multipart/x-mixed-replace MJPEG straight through
// to the browser. Each tab gets its own subscription on the bridge; the
// bridge fans frames from one ffmpeg process to all connected tabs.

import type { APIRoute } from "astro";
import { request as httpRequest } from "node:http";

export const prerender = false;
const SOCK = process.env.BAMBU_BRIDGE_SOCK;

export const GET: APIRoute = async () => {
  if (!SOCK) return jsonError(503, "bridge_not_configured", "BAMBU_BRIDGE_SOCK unset");
  return await new Promise<Response>((resolve) => {
    const req = httpRequest(
      { socketPath: SOCK, path: "/camera/stream.mjpg", method: "GET" },
      (res) => {
        if (res.statusCode !== 200) {
          // Not streaming — drain JSON error and respond with it.
          const chunks: Buffer[] = [];
          res.on("data", (c: Buffer) => chunks.push(c));
          res.on("end", () =>
            resolve(
              new Response(Buffer.concat(chunks), {
                status: res.statusCode ?? 502,
                headers: { "content-type": res.headers["content-type"] ?? "application/json" },
              }),
            ),
          );
          return;
        }
        const stream = new ReadableStream({
          start(controller) {
            res.on("data", (c: Buffer) => controller.enqueue(new Uint8Array(c)));
            res.on("end", () => {
              try { controller.close(); } catch {}
            });
            res.on("error", (err) => {
              try { controller.error(err); } catch {}
            });
          },
          cancel() {
            res.destroy();
          },
        });
        resolve(
          new Response(stream, {
            status: 200,
            headers: {
              "content-type":
                res.headers["content-type"] ?? "multipart/x-mixed-replace; boundary=bambuframe",
              "cache-control": "no-store",
            },
          }),
        );
      },
    );
    req.on("error", (err: NodeJS.ErrnoException) =>
      resolve(jsonError(503, err.code === "ENOENT" ? "bridge_offline" : "bridge_unreachable", err.message)),
    );
    req.end();
  });
};

function jsonError(status: number, code: string, detail: string): Response {
  return new Response(JSON.stringify({ error: code, detail }), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}
