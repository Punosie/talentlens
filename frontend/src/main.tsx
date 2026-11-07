import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router'
import App from './App'
import { ToastProvider } from './components/ui'
import './index.css'
import AddPage from './pages/Add'
import HelpPage from './pages/Help'
import HomePage from './pages/Home'
import MatchPage from './pages/Match'
import SavedPage from './pages/Saved'
import SearchPage from './pages/Search'
import SettingsPage from './pages/Settings'
import { UploadProvider } from './upload/UploadContext'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, refetchOnWindowFocus: false, retry: 1 } },
})

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'search', element: <SearchPage /> },
      { path: 'match', element: <MatchPage /> },
      { path: 'add', element: <AddPage /> },
      { path: 'saved', element: <SavedPage /> },
      { path: 'saved/:id', element: <SavedPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: 'help', element: <HelpPage /> },
      // v0.1 addresses
      { path: 'shortlist', element: <Navigate to="/match" replace /> },
      { path: 'upload', element: <Navigate to="/add" replace /> },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <UploadProvider>
          <RouterProvider router={router} />
        </UploadProvider>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
)
