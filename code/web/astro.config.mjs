// @ts-check
import { defineConfig } from 'astro/config';
import node from '@astrojs/node';

// Hybrid build: most pages stay prerendered as static HTML (the
// gallery cards read GLB + YAML at build time). The `/api/open`
// endpoint marks `prerender = false` so it runs on the Astro
// server at request time — needed so the dev gallery can spawn
// `openscad` / `kicad` locally when the user clicks the action.
// The Node adapter is required for the build to wire up SSR.
export default defineConfig({
  output: 'server',
  adapter: node({ mode: 'standalone' }),
});
