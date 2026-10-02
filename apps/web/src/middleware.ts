import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// This middleware runs on the server
// It protects routes that require authentication

const publicPaths = [
  '/login',
  '/register',
  '/verify-email',
  '/forgot-password',
  '/reset-password',
  '/api/auth/login',
  '/api/auth/register',
  '/api/auth/verify-email',
  '/api/auth/forgot-password',
  '/api/auth/reset-password',
  '/api/health',
  '/api/health/ready',
];

const authPaths = [
  '/login',
  '/register',
  '/verify-email',
  '/forgot-password',
  '/reset-password',
];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  
  // Check if path is public
  const isPublicPath = publicPaths.some(path => pathname.startsWith(path));
  
  // Check if path is an auth path (should redirect if authenticated)
  const isAuthPath = authPaths.some(path => pathname.startsWith(path));
  
  // Get session cookie
  const sessionCookie = request.cookies.get('oa_session');
  
  // For auth paths, if user has session, redirect to dashboard
  if (isAuthPath && sessionCookie) {
    // We can't verify the session here without calling the API
    // The client-side auth context will handle this
    return NextResponse.next();
  }
  
  // For protected paths, we rely on client-side auth check
  // The server API will enforce authentication
  
  // Add security headers
  const response = NextResponse.next();
  
  // Security headers
  response.headers.set('X-Content-Type-Options', 'nosniff');
  response.headers.set('X-Frame-Options', 'DENY');
  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
  
  // CSP - adjust as needed
  response.headers.set(
    'Content-Security-Policy',
    "default-src 'self'; script-src 'self' 'unsafe-eval' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' http://localhost:8000 https://api.openagent.local;"
  );
  
  return response;
}

export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     * - public folder
     */
    '/((?!_next/static|_next/image|favicon.ico|public/).*)',
  ],
};