'use client';

import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { api, ApiError } from '@/lib/api';

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  avatar_url: string | null;
  status: string;
  email_verified: boolean;
  is_superadmin: boolean;
  is_platform_owner: boolean;
  created_at: string;
}

export interface Session {
  id: string;
  user_agent: string | null;
  ip_address: string | null;
  created_at: string;
  last_seen_at: string | null;
  expires_at: string;
  current: boolean;
}

interface AuthState {
  status: 'loading' | 'authenticated' | 'unauthenticated';
  user: User | null;
  isLoading: boolean;
  error: string | null;
}

interface AuthContextType extends AuthState {
  login: (email: string, password: string, rememberMe?: boolean) => Promise<void>;
  register: (email: string, password: string, displayName?: string) => Promise<unknown>;
  logout: (logoutAll?: boolean) => Promise<void>;
  verifyEmail: (token: string) => Promise<void>;
  forgotPassword: (email: string) => Promise<void>;
  resetPassword: (token: string, password: string) => Promise<void>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  fetchUser: () => Promise<void>;
  fetchSessions: () => Promise<Session[]>;
  revokeSession: (sessionId: string) => Promise<void>;
  clearError: () => void;
  sessions?: Session[];
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    status: 'loading',
    user: null,
    isLoading: true,
    error: null,
  });

  const [sessions, setSessions] = useState<Session[]>([]);

  const clearError = useCallback(() => {
    setState(prev => ({ ...prev, error: null }));
  }, []);

  const setError = useCallback((error: string | null) => {
    setState(prev => ({ ...prev, error }));
  }, []);

  const setUser = useCallback((user: User | null) => {
    setState(prev => ({
      ...prev,
      user,
      status: user ? 'authenticated' : 'unauthenticated',
      isLoading: false,
    }));
  }, []);

  const fetchUser = useCallback(async () => {
    try {
      setState(prev => ({ ...prev, isLoading: true }));
      const data = await api.get<User | { user: User }>('/auth/me');
      const user = (data as { user?: User }).user ?? (data as User);
      if (user && (user as User).id) setUser(user as User);
      else setUser(null);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setUser(null);
      } else {
        setUser(null);
        console.error('Failed to fetch user:', error);
      }
    }
  }, [setUser]);

  const login = useCallback(async (email: string, password: string, rememberMe = false) => {
    try {
      setState(prev => ({ ...prev, isLoading: true, error: null }));
      const data = await api.post<{ user: User; session_token: string; expires_at: string }>('/auth/login', {
        email,
        password,
        remember_me: rememberMe,
      });

      // The session cookie is set by the server; normalize user shape.
      const raw = data.user as Partial<User>;
      const u: User = {
        id: String(raw.id ?? ''),
        email: String(raw.email ?? email),
        display_name: (raw.display_name as string | null) ?? null,
        avatar_url: (raw.avatar_url as string | null) ?? null,
        status: String(raw.status ?? 'active'),
        email_verified: Boolean(raw.email_verified),
        is_superadmin: Boolean(raw.is_superadmin),
        is_platform_owner: Boolean(raw.is_platform_owner),
        created_at: String(raw.created_at ?? new Date().toISOString()),
      };
      setUser(u);
    } catch (error) {
      setState(prev => ({ ...prev, isLoading: false }));
      if (error instanceof ApiError) {
        setError(error.message);
        throw error;
      }
      throw error;
    }
  }, [setUser, setError]);

  const register = useCallback(async (email: string, password: string, displayName?: string) => {
    try {
      setState(prev => ({ ...prev, isLoading: true, error: null }));
      const data = await api.post<{ user_id: string; verification_sent: boolean }>('/auth/register', {
        email,
        password,
        display_name: displayName,
      });
      
      setState(prev => ({ ...prev, isLoading: false }));
      return data;
    } catch (error) {
      setState(prev => ({ ...prev, isLoading: false }));
      if (error instanceof ApiError) {
        setError(error.message);
        throw error;
      }
      throw error;
    }
  }, [setError]);

  const logout = useCallback(async (logoutAll = false) => {
    try {
      setState(prev => ({ ...prev, isLoading: true }));
      await api.post('/auth/logout', { logout_all: logoutAll });
      setUser(null);
    } catch (error) {
      setUser(null);
      console.error('Logout failed:', error);
    }
  }, [setUser]);

  const verifyEmail = useCallback(async (token: string) => {
    try {
      setState(prev => ({ ...prev, isLoading: true, error: null }));
      await api.post('/auth/verify-email', { token });
      setState(prev => ({ ...prev, isLoading: false }));
    } catch (error) {
      setState(prev => ({ ...prev, isLoading: false }));
      if (error instanceof ApiError) {
        setError(error.message);
        throw error;
      }
      throw error;
    }
  }, [setError]);

  const forgotPassword = useCallback(async (email: string) => {
    try {
      setState(prev => ({ ...prev, isLoading: true, error: null }));
      await api.post('/auth/forgot-password', { email });
      setState(prev => ({ ...prev, isLoading: false }));
    } catch (error) {
      setState(prev => ({ ...prev, isLoading: false }));
      if (error instanceof ApiError) {
        setError(error.message);
        throw error;
      }
      throw error;
    }
  }, [setError]);

  const resetPassword = useCallback(async (token: string, password: string) => {
    try {
      setState(prev => ({ ...prev, isLoading: true, error: null }));
      await api.post('/auth/reset-password', { token, password });
      setState(prev => ({ ...prev, isLoading: false }));
    } catch (error) {
      setState(prev => ({ ...prev, isLoading: false }));
      if (error instanceof ApiError) {
        setError(error.message);
        throw error;
      }
      throw error;
    }
  }, [setError]);

  const changePassword = useCallback(async (currentPassword: string, newPassword: string) => {
    try {
      setState(prev => ({ ...prev, isLoading: true, error: null }));
      await api.post('/auth/change-password', { current_password: currentPassword, new_password: newPassword });
      setState(prev => ({ ...prev, isLoading: false }));
    } catch (error) {
      setState(prev => ({ ...prev, isLoading: false }));
      if (error instanceof ApiError) {
        setError(error.message);
        throw error;
      }
      throw error;
    }
  }, [setError]);

  const fetchSessions = useCallback(async () => {
    try {
      const data = await api.get<{ sessions: Session[] }>('/auth/sessions');
      setSessions(data.sessions);
      return data.sessions;
    } catch (error) {
      console.error('Failed to fetch sessions:', error);
      return [];
    }
  }, []);

  const revokeSession = useCallback(async (sessionId: string) => {
    try {
      await api.delete(`/auth/sessions/${sessionId}`);
      setSessions(prev => prev.filter(s => s.id !== sessionId));
    } catch (error) {
      if (error instanceof ApiError) {
        setError(error.message);
        throw error;
      }
      throw error;
    }
  }, [setError]);

  // Initialize auth on mount
  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  return (
    <AuthContext.Provider value={{
      ...state,
      login,
      register,
      logout,
      verifyEmail,
      forgotPassword,
      resetPassword,
      changePassword,
      fetchUser,
      fetchSessions,
      revokeSession,
      clearError,
      sessions,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}