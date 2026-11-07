import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router'
import App from './App'
import { ToastProvider } from './components/ui'
import './index.css'
import LibraryPage from './pages/Library'
import SavedPage from './pages/Saved'
import ShortlistPage from './pages/Shortlist'
import UploadPage from './pages/Upload'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, refetchOnWindowFocus: false, retry: 1 } },
})

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <LibraryPage /> },
      { path: 'upload', element: <UploadPage /> },
      { path: 'shortlist', element: <ShortlistPage /> },
      { path: 'saved', element: <SavedPage /> },
      { path: 'saved/:id', element: <SavedPage /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
)
