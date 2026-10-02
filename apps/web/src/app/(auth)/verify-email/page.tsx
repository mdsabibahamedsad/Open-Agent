'use client';

export const dynamic = 'force-dynamic';

import { useEffect, useState, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/context/AuthContext';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Loader2, CheckCircle, AlertCircle } from 'lucide-react';

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
      <VerifyContent />
    </Suspense>
  );
}

function VerifyContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { verifyEmail } = useAuth();
  const [status, setStatus] = useState<'verifying' | 'success' | 'error'>('verifying');
  const [message, setMessage] = useState('');
  const [email, setEmail] = useState('');

  useEffect(() => {
    const token = searchParams.get('token');
    const emailParam = searchParams.get('email');
    
    if (emailParam) {
      setEmail(emailParam);
    }

    if (token) {
      verifyEmail(token)
        .then(() => {
          setStatus('success');
          setMessage('Your email has been verified successfully!');
        })
        .catch((error) => {
          setStatus('error');
          setMessage(error.message || 'Verification failed. The link may have expired or already been used.');
        });
    } else {
      setStatus('error');
      setMessage('Invalid verification link. Please check your email for the correct link.');
    }
  }, [searchParams, verifyEmail]);

  const handleResend = async () => {
    // In a real app, you'd call a resend verification endpoint
    setMessage('If an account exists, a new verification email has been sent.');
  };

  if (status === 'verifying') {
    return (
      <Card>
        <CardHeader className="text-center">
          <CardTitle className="text-2xl font-bold">Verifying your email</CardTitle>
          <CardDescription>Please wait while we verify your email address...</CardDescription>
        </CardHeader>
        <CardContent className="flex justify-center py-8">
          <Loader2 className="w-8 h-8 text-indigo-600 animate-spin" />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="text-center">
          <div className={`mx-auto w-16 h-16 rounded-full flex items-center justify-center ${
            status === 'success' ? 'bg-green-100 text-green-600' : 'bg-red-100 text-red-600'
          }`}>
            {status === 'success' ? (
              <CheckCircle className="w-8 h-8" />
            ) : (
              <AlertCircle className="w-8 h-8" />
            )}
          </div>
          <CardTitle className="mt-4 text-2xl font-bold">
            {status === 'success' ? 'Email Verified!' : 'Verification Failed'}
          </CardTitle>
          <CardDescription>{message}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {status === 'success' && (
            <div className="space-y-3">
              <Button onClick={() => router.push('/dashboard')} className="w-full">
                Continue to Dashboard
              </Button>
              <Button variant="outline" onClick={() => router.push('/login')} className="w-full">
                Sign In
              </Button>
            </div>
          )}

          {status === 'error' && (
            <div className="space-y-3">
              <Button onClick={() => router.push('/login')} className="w-full">
                Try Signing In
              </Button>
              <Button variant="outline" onClick={handleResend} className="w-full">
                Resend Verification Email
              </Button>
              <Link href="/register" className="text-center text-sm text-indigo-600 hover:text-indigo-500">
                Create a new account
              </Link>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}