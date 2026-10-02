import { NextRequest, NextResponse } from 'next/server';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

export async function GET(request: NextRequest) {
  return proxyRequest(request, 'GET');
}

export async function DELETE(request: NextRequest) {
  return proxyRequest(request, 'DELETE');
}

async function proxyRequest(request: NextRequest, method: string) {
  const url = `${API_BASE}/auth/sessions`;
  
  // Get search params for query parameters
  const searchParams = request.nextUrl.searchParams.toString();
  const fullUrl = searchParams ? `${url}?${searchParams}` : url;
  
  // Forward headers
  const headers: HeadersInit = {};
  request.headers.forEach((value, key) => {
    if (key.toLowerCase() !== 'host') {
      headers[key] = value;
    }
  });
  
  if (method !== 'GET' && method !== 'DELETE') {
    headers['Content-Type'] = 'application/json';
  }
  
  let body: string | undefined;
  if (method !== 'GET' && method !== 'DELETE') {
    try {
      body = await request.text();
    } catch {
      // No body
    }
  }
  
  try {
    const response = await fetch(fullUrl, {
      method,
      headers,
      body,
      credentials: 'omit',
    });
    
    const data = await response.json().catch(() => ({}));
    
    const nextResponse = NextResponse.json(data, { status: response.status });
    
    response.headers.getSetCookie().forEach(cookie => {
      nextResponse.headers.append('Set-Cookie', cookie);
    });
    
    return nextResponse;
  } catch (error) {
    console.error('API proxy error:', error);
    return NextResponse.json(
      { error: { message: 'Failed to connect to API', code: 'API_UNAVAILABLE' } },
      { status: 503 }
    );
  }
}