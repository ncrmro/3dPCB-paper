// @ts-check
import { defineConfig } from 'astro/config';
import node from '@astrojs/node';
import { existsSync, statSync, watch } from 'node:fs';
import { resolve, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

// Hybrid build: most pages stay prerendered as static HTML (the
// gallery cards read GLB + YAML at build time). The `/api/open`
// endpoint marks `prerender = false` so it runs on the Astro
// server at request time — needed so the dev gallery can spawn
// `openscad` / `kicad` locally when the user clicks the action.
// The Node adapter is required for the build to wire up SSR.

const HERE = fileURLToPath(new URL('.', import.meta.url));
const PUBLIC_CAD_DIR = resolve(HERE, 'public/models/cad');
const REPORTS_DIR = resolve(HERE, 'src/reports');
const SPECS_DIR = resolve(HERE, '../cad/specs');

/**
 * Dev-only Vite plugin that watches the staged GLBs + report JSONs
 * and pushes a custom HMR event so the focus / index pages can
 * swap the model-viewer's `src` (with a fresh ?t=<mtime> cache
 * buster) instead of forcing a hard reload. The previous behaviour
 * — `?v=Date.now()` baked at SSR time — only updated on a page
 * reload, which made the watch-cad loop feel disconnected.
 *
 * - GLB change → `glb-changed` event with `{ path, mtime }`.
 *   `path` is the public URL ("/models/cad/<stem>.glb") so the
 *   browser can match it against a `<model-viewer src>` directly.
 * - Report JSON change → `report-changed` event. The page reloads
 *   itself; rerunning the SSR is the cheapest way to pick up the
 *   updated ?raw-imported JSON.
 *
 * fs.watch is debounced 200 ms to coalesce editor-save bursts. The
 * spec watcher exists so a manual edit to a YAML (outside the
 * gallery editor) also triggers the reload chain.
 */
function glbHotReloadPlugin() {
  return {
    name: 'glb-hot-reload',
    apply: /** @type {const} */ ('serve'),
    configureServer(server) {
      /** @type {Map<string, NodeJS.Timeout>} */
      const pending = new Map();
      const debounce = (key, fn) => {
        const prev = pending.get(key);
        if (prev) clearTimeout(prev);
        pending.set(
          key,
          setTimeout(() => {
            pending.delete(key);
            fn();
          }, 200),
        );
      };

      const startWatch = (dir, onChange) => {
        if (!existsSync(dir)) {
          server.config.logger.warn(`[glb-hot-reload] missing dir: ${dir}`);
          return;
        }
        try {
          // recursive: works on macOS+Windows out of the box; on Linux
          // fs.watch's recursive mode landed in Node 20. The dirs we
          // watch are flat, so plain (non-recursive) watch also works.
          const w = watch(dir, { persistent: true }, (_event, filename) => {
            if (!filename) return;
            const full = resolve(dir, filename.toString());
            if (!existsSync(full)) return;
            debounce(full, () => onChange(full));
          });
          server.httpServer?.once('close', () => w.close());
        } catch (e) {
          server.config.logger.warn(`[glb-hot-reload] watch ${dir} failed: ${e}`);
        }
      };

      startWatch(PUBLIC_CAD_DIR, (full) => {
        if (!full.endsWith('.glb')) return;
        const rel = relative(PUBLIC_CAD_DIR, full);
        const publicPath = `/models/cad/${rel}`;
        let mtime = Date.now();
        try {
          mtime = Math.floor(statSync(full).mtimeMs);
        } catch {}
        server.ws.send({ type: 'custom', event: 'glb-changed', data: { path: publicPath, mtime } });
        server.config.logger.info(`[glb-hot-reload] pushed glb-changed ${publicPath}`);
      });

      startWatch(REPORTS_DIR, (full) => {
        if (!full.endsWith('.json')) return;
        server.ws.send({ type: 'custom', event: 'report-changed', data: { path: full } });
      });

      startWatch(SPECS_DIR, (full) => {
        if (!full.endsWith('.yaml')) return;
        // No direct browser action — the watch-cad process picks up
        // the YAML change and rebuilds the GLB, which fires the
        // glb-changed event above. Log only.
        server.config.logger.info(`[glb-hot-reload] spec changed: ${full}`);
      });
    },
  };
}

export default defineConfig({
  output: 'server',
  adapter: node({ mode: 'standalone' }),
  // Dev server: bind every interface and accept any Host header.
  // Default Astro/Vite refuses requests whose Host doesn't match the
  // listen address — fine for laptop work, useless across a LAN.
  server: {
    host: '0.0.0.0',
  },
  vite: {
    plugins: [glbHotReloadPlugin()],
    server: {
      // `true` = allow every Host header. Dev-only; the deployed
      // Node adapter does its own host validation.
      allowedHosts: true,
    },
  },
});
