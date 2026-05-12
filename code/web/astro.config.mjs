// @ts-check
import { defineConfig } from 'astro/config';

// Static build: the gallery reads GLBs and a YAML manifest emitted by the
// render pipelines (PRs E/F) at build time. No SSR is needed.
export default defineConfig({
  output: 'static',
});
