import React, { useState, useEffect, createContext, useContext } from 'react';
import ReportPage from './components/ReportPage';

// Auth context for managing session state
interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  login: () => void;
  logout: () => void;
  checkSession: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};

// Auth Provider component
const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  const AUTH_URL = process.env.REACT_APP_AUTH_URL || 'http://localhost:8001';

  const checkSession = async () => {
    try {
      const response = await fetch(`${AUTH_URL}/auth/session`, {
        credentials: 'include',  // Include cookies
      });

      if (response.ok) {
        const data = await response.json();
        setIsAuthenticated(data.authenticated);
      } else {
        setIsAuthenticated(false);
      }
    } catch (error) {
      console.error('Session check failed:', error);
      setIsAuthenticated(false);
    } finally {
      setIsLoading(false);
    }
  };

  const login = () => {
    // Redirect to auth service login endpoint
    window.location.href = `${AUTH_URL}/auth/login`;
  };

  const logout = async () => {
    try {
      // Call logout endpoint
      window.location.href = `${AUTH_URL}/auth/logout`;
    } catch (error) {
      console.error('Logout failed:', error);
    }
  };

  useEffect(() => {
    checkSession();
  }, []);

  return (
    <AuthContext.Provider value={{ isAuthenticated, isLoading, login, logout, checkSession }}>
      {children}
    </AuthContext.Provider>
  );
};

const App: React.FC = () => {
  return (
    <AuthProvider>
      <div className="App">
        <ReportPage />
      </div>
    </AuthProvider>
  );
};

export default App;
