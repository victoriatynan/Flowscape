import { defineConfig } from 'vitest/config'

// Vitest config for the presentation-layer tests (M4). jsdom gives the analysis
// components a DOM to render into; the setup file wires jest-dom matchers.
export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
