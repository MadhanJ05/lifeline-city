/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the local API; defaults to http://localhost:8000 in src/api.ts. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
