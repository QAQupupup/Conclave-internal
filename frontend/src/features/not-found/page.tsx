import * as React from 'react';
import { Link } from 'react-router';
import { Button } from '@/components/ui/button';

export default function NotFoundPage() {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-4 bg-bg-secondary">
      <h1 className="text-5xl font-bold text-text-tertiary">404</h1>
      <p className="text-sm text-text-secondary">页面不存在</p>
      <Link to="/board">
        <Button variant="outline" size="sm">返回看板</Button>
      </Link>
    </div>
  );
}
