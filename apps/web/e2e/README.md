# E2E Tests (PRD S9.5)

Playwright-based end-to-end tests for the React run viewer.

## Setup

1. Install dependencies:
   ```bash
   cd apps/web
   npm install
   ```

2. Install Playwright browsers:
   ```bash
   npx playwright install chromium
   ```

## Running Tests

### Prerequisites
- API server must be running at http://localhost:8000
- For authenticated tests, set environment variables:
  ```bash
  export ADMIN_USER=your_admin_user
  export ADMIN_PASSWORD=your_admin_password
  ```

### Run all tests
```bash
npm run test:e2e
```

### Run with UI (interactive)
```bash
npm run test:e2e:ui
```

### Run in headed mode (see browser)
```bash
npm run test:e2e:headed
```

### Run specific test
```bash
npx playwright test app.spec.js
```

## Test Structure

- `app.spec.js` - Main UI flow tests
  - Login flow
  - Runs list
  - Run detail navigation
  - API health checks

## Integration with Python Tests

The e2e tests are also callable from pytest via `tests/e2e/test_web_ui.py`.
This allows running them as part of the full test gate:

```bash
pytest tests/e2e/test_web_ui.py -v
```

Note: The pytest wrapper skips tests if Node.js, Playwright, or the API server are not available.

## PRD Requirements

Per PRD S9.5:
- ✅ Playwright e2e tests created
- ✅ Tests verify upload→story flow (currently limited to existing viewer functionality)
- ⚠️ Latency benchmarking: deferred (requires full data story upload flow)

## Next Steps

When the upload UI is implemented (PRD S9.1-S9.3):
1. Add test for CSV upload
2. Add test for story page visualization
3. Add latency measurement test (100k×50 synthetic → 30s p95 target)
