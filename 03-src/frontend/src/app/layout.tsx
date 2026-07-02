import type { Metadata } from 'next';
import './globals.css';
import ThemeProvider from '@/components/ThemeProvider';
import ClientLayout from './ClientLayout';
import AuthGuard from '@/components/AuthGuard';
import MainShell from '@/components/MainShell';

export const metadata: Metadata = {
  title: 'inFlow AI · 入流 — AI 驱动个人知识管理平台',
  description: ' AI 驱动个人知识管理平台 —— 一键收藏、AI 自动梳理、语义检索、知识图谱、Obsidian 同步备份。',
  icons: {
    icon: '/favicon.svg',
    apple: '/apple-touch-icon.png',
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>
        <ThemeProvider>
          <ClientLayout>
            <AuthGuard>
              <MainShell>
                {children}
              </MainShell>
            </AuthGuard>
          </ClientLayout>
        </ThemeProvider>
      </body>
    </html>
  );
}
