import * as React from 'react';
import { Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Link } from 'react-router';

export default function LandingPage() {
  return (
    <div className="flex h-screen items-center justify-center bg-bg-secondary">
      <div className="text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-lg bg-brand-500 text-white shadow-sm">
          <Sparkles className="h-7 w-7" />
        </div>
        <h1 className="text-2xl font-semibold text-text-primary">Conclave</h1>
        <p className="mt-2 text-sm text-text-tertiary">AI 智库 · 多 Agent 协同探索系统</p>
        <Link to="/board" className="mt-6 inline-block">
          <Button>进入系统</Button>
        </Link>
      </div>
    </div>
  );
}
