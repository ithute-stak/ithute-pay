import { defineConfig } from '@playwright/test';
export default defineConfig({
 testDir: './e2e/tenant',
 use: { baseURL: 'http://localhost:3001' },
 webServer: { command: 'pnpm dev', url: 'http://localhost:3001/business', reuseExistingServer: !process.env.CI, timeout: 120000 },
});
