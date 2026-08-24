'use client';

import { useEffect, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft, Loader2 } from 'lucide-react';
import { api } from '@/lib/api';

/**
 * Redirect trampoline: article_id is always set the moment a job is created,
 * so the first poll almost always resolves immediately. This page is a brief
 * loading screen while waiting for that first API response.
 *
 * For legacy jobs (created before this architecture change) article_id may
 * be null during early stages — we keep polling until it appears.
 */
export default function ProcessingPage() {
  const params = useParams();
  const router = useRouter();
  const jobId = params.job_id as string;

  const check = useCallback(async () => {
    try {
      const job = await api.getIngestJob(jobId);
      if (job.article_id) {
        router.replace(`/read/${job.article_id}?job=${jobId}`);
      }
    } catch {
      // Retry silently on network errors
    }
  }, [jobId, router]);

  useEffect(() => {
    check();
    const iv = setInterval(check, 2000);
    return () => clearInterval(iv);
  }, [check]);

  return (
    <div className="min-h-screen bg-[var(--bg-primary)] flex flex-col">
      <div className="sticky top-0 z-30 bg-[#f5f5f7]/80 backdrop-blur-xl border-b border-[#e5e5ea]">
        <div className="max-w-3xl mx-auto px-3 sm:px-6 h-12 flex items-center">
          <Link
            href="/library"
            className="flex items-center gap-1.5 text-sm text-[#6e6e73] hover:text-[#1d1d1f] transition-colors"
          >
            <ArrowLeft size={16} />
            <span className="hidden sm:inline">返回</span>
          </Link>
        </div>
      </div>
      <div className="flex-1 flex flex-col items-center justify-center gap-4 text-[var(--text-secondary)]">
        <Loader2 size={32} className="animate-spin text-[var(--accent)]" />
        <p className="text-sm">正在跳转…</p>
      </div>
    </div>
  );
}
