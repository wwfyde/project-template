import {defineConfig} from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from "@tailwindcss/vite";
import {tanstackRouter} from "@tanstack/router-plugin/vite";
import {codeInspectorPlugin} from "code-inspector-plugin";
import {devServerOptions} from './config/dev-server.ts'

// https://vite.dev/config/
export default defineConfig(({mode}) => ({
  server: devServerOptions(mode, import.meta.dirname),
  plugins: [
    tailwindcss(),
    tanstackRouter({
      target: 'react',
      autoCodeSplitting: true,
    }), // 必须在react之前
    codeInspectorPlugin({
      bundler: "vite",
      editor: "code", // pycharm, cursor
      behavior: {
        locate: true,
      },
    }),
    react(),
  ],
  resolve: {
    tsconfigPaths: true,
    // Hoisted workspace dependencies can carry their own React peer copies.
    dedupe: ['react', 'react-dom'],
    // alias: {
    //   '@': fileURLToPath(new URL('./src', import.meta.url)),
    // },
  },

}))
