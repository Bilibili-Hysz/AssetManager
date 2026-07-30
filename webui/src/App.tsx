import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './stores/AuthContext';
import { RealtimeProvider } from './stores/RealtimeContext';
import { ToastProvider } from './components/ui/Toast';
import { DownloadProgressProvider } from './components/ui/DownloadProgress';
import LandingPage from './pages/LandingPage';
import LoginPage from './pages/LoginPage';
import BrowsePage from './pages/BrowsePage';
import DetailPage from './pages/DetailPage';
import ShareReceivePage from './pages/ShareReceivePage';

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <RealtimeProvider>
          <ToastProvider>
            <DownloadProgressProvider>
              <Routes>
                <Route path="/" element={<LandingPage />} />
                <Route path="/login" element={<LoginPage />} />
                <Route path="/browse" element={<BrowsePage />} />
                <Route path="/detail" element={<DetailPage />} />
                <Route path="/s/:shareId" element={<ShareReceivePage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </DownloadProgressProvider>
          </ToastProvider>
        </RealtimeProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
