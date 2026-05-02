import { createRoot } from 'react-dom/client'
import { HashRouter } from 'react-router'
import { Toaster } from 'sonner'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <HashRouter>
    <App />
    <Toaster
      position="top-right"
      toastOptions={{
        style: {
          background: '#0D1320',
          border: '1px solid #152033',
          color: '#F0F4F8',
        },
      }}
    />
  </HashRouter>,
)
