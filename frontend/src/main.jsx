import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'sonner';
import App from './app/App';
import './styles/globals.css';
import './styles/layout.css';
import './styles/components.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60 * 1000,        // 1 minute — SIC data refreshes periodically
      refetchOnWindowFocus: false,  // Don't spam backend on tab switch
      retry: 2,
    },
  },
});

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
        <Toaster
          position="top-right"
          theme="light"
          richColors
          closeButton
          toastOptions={{
            style: {
              background: 'var(--color-bg-card)',
              border: '1px solid var(--color-border-primary)',
              color: 'var(--color-text-primary)',
            },
          }}
        />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
