import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import {nodePolyfills} from 'vite-plugin-node-polyfills';
import {fileURLToPath, URL} from 'node:url';

export default defineConfig({
  plugins: [
    react(),
    nodePolyfills({
      include: ['assert', 'events'],
      globals: {
        Buffer: true,
        global: true,
        process: true
      }
    })
  ],
  resolve: {
    alias: [
      {
        find: /^maplibre-gl$/,
        replacement: fileURLToPath(
          new URL('./node_modules/maplibre-gl/dist/maplibre-gl.mjs', import.meta.url)
        )
      }
    ]
  },
  server: {
    host: '127.0.0.1',
    port: 4173
  },
  preview: {
    host: '127.0.0.1',
    port: 4173
  },
  build: {
    chunkSizeWarningLimit: 3000
  }
});
