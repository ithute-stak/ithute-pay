import { defineConfig } from '@playwright/test';
export default defineConfig({
 testDir: './e2e/tenant',
 use: { baseURL: 'http://127.0.0.1:3001' },
 webServer: { command: 'pnpm dev', url: 'http://127.0.0.1:3001/business', reuseExistingServer: !process.env.CI, timeout: 120000 },
});
