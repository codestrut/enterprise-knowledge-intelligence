# EKIP frontend development

Run frontend commands from this directory:

```sh
npm run dev
npm run check
npm test
npm run build
```

## Browser smoke test

The repeatable Playwright smoke test starts Vite on `127.0.0.1:4173` and routes API requests through Vite to the isolated test API at `http://127.0.0.1:8002`. The isolated API must already be running. The test checks the visible overview, navigation, and API connectivity using only health and document-list reads; it does not upload, delete, or modify documents.

```sh
npm run test:e2e
```

To set the proxy target explicitly:

```sh
EKIP_API_PROXY_TARGET=http://127.0.0.1:8002 npm run test:e2e
```

Playwright rejects port `8000` and any target that is not a loopback address on port `8002`. The browser itself uses the Vite origin on port `4173`; API calls are same-origin `/api/...` requests handled by the Vite proxy.
