// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import React from 'react';
import ReactDOM from 'react-dom/client';
import { Notifications } from '@mantine/notifications';
import { QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';

// The floating devtools button overlaps with form-bottom Save buttons
// in e2e tests and intercepts pointer events. Opt in explicitly via
// localStorage so day-to-day dev work isn't bothered either.
const DEVTOOLS_ENABLED =
  typeof window !== 'undefined' &&
  window.localStorage?.getItem('atrium-devtools') === '1';
import { BrowserRouter } from 'react-router-dom';
import '@mantine/core/styles.css';
import '@mantine/dates/styles.css';
import '@mantine/notifications/styles.css';
import './styles/global.css';

import App from './App';
// Importing the registry module installs ``window.__ATRIUM_REGISTRY__``
// as a side-effect; the host bundle reads from there. Must run before
// the dynamic import below so the host bundle's import-time
// registration calls find the global already populated.
import './host/registry';
import { api } from './lib/api';
import { queryClient } from './lib/queryClient';
import { ThemedApp } from './theme/ThemedApp';
import './i18n';

// Host bundles externalise React + ReactDOM (per the Vite config in
// docs/published-images.md) so their import-time code can call
// ``React.createElement`` without doubling up on the React copy. We
// expose the SPA's React instance on ``window`` for them to pick up;
// without this, an externalised bundle would resolve to ``undefined``
// at runtime.
declare global {
  interface Window {
    React?: typeof React;
  }
}
if (typeof window !== 'undefined') {
  window.React = React;
}

interface BootSystemSlice {
  host_bundle_url?: string | null;
}

interface BootAppConfig {
  system?: BootSystemSlice;
}

async function loadHostBundle(): Promise<void> {
  let url: string | null | undefined;
  try {
    const { data } = await api.get<BootAppConfig>('/app-config');
    url = data?.system?.host_bundle_url ?? null;
  } catch (err) {
    // /app-config is the same call useAppConfig() makes once React
    // mounts; if it's down here it'll surface there too. Don't block
    // the app from rendering on a transient backend hiccup.
    console.warn('[atrium] /app-config probe failed during boot', err);
    return;
  }
  if (!url) return;
  try {
    // The host bundle's import-time side-effects call
    // window.__ATRIUM_REGISTRY__.register*. By the time this await
    // resolves every registration is in place, so the consumer
    // components see a populated registry on first render.
    await import(/* @vite-ignore */ url);
  } catch (err) {
    // Bundle-load failure is non-fatal: the SPA still renders, just
    // without the host extensions. The error is logged so an admin
    // who fat-fingered the URL can find it in the browser console.
    console.error('[atrium] host bundle failed to load', url, err);
  }
}

async function bootstrap(): Promise<void> {
  await loadHostBundle();
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <ThemedApp>
          <Notifications position="top-right" />
          <BrowserRouter>
            <App />
          </BrowserRouter>
          {DEVTOOLS_ENABLED && <ReactQueryDevtools initialIsOpen={false} />}
        </ThemedApp>
      </QueryClientProvider>
    </React.StrictMode>,
  );
}

void bootstrap();
