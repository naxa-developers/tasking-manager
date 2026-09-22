import { Outlet, useLocation } from 'react-router-dom';
import { QueryParamProvider } from 'use-query-params';
import { ReactRouter6Adapter } from 'use-query-params/adapters/react-router-6';

import { TopBanner } from '../components/banner/topBanner';
import { Header } from '../components/header';
import { Footer } from '../components/footer';
import { ChatLauncher } from '../components/ragChat/ChatLauncher';

// Including components that use React Router hooks here
// Components common to all routes can be included in <App>
export function Root() {
  const location = useLocation();
  const isChatRoute = location.pathname === '/chat' || location.pathname.startsWith('/chat/');
  return (
    <div className="flex flex-column">
      <TopBanner />
      <Header />
      <QueryParamProvider adapter={ReactRouter6Adapter}>
        <Outlet />
      </QueryParamProvider>
      <Footer />
      {!isChatRoute && <ChatLauncher />}
    </div>
  );
}
