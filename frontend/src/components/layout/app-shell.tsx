import * as React from 'react';
import { Outlet, useLocation } from 'react-router';
import { TopBar } from './top-bar';
import { NavRail } from './nav-rail';
import { StatusBar } from './status-bar';
import { CommandPalette } from './command-palette';

export function AppShell() {
  const location = useLocation();
  const isInMeeting = location.pathname.startsWith('/meeting/');
  return (
    <div className="flex h-screen flex-col bg-bg-primary text-text-primary">
      <TopBar />
      <div className="flex flex-1 overflow-hidden">
        <NavRail />
        <main className={isInMeeting ? 'flex flex-1 overflow-hidden' : 'flex-1 overflow-auto bg-bg-secondary'}>
          <Outlet />
        </main>
      </div>
      <StatusBar />
      <CommandPalette />
    </div>
  );
}
