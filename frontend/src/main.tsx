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
import { queryClient } from './lib/queryClient';
import { ThemedApp } from './theme/ThemedApp';
import './i18n';

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
