'use client';
import * as React from 'react';
import { usePathname } from 'next/navigation';
import { usePreference } from '@mui/internal-docs-infra/usePreference';
import { GoogleAnalyticsProvider } from 'docs-mdx/src/blocks/GoogleAnalyticsProvider';
import { GoogleTagManager } from '../blocks/GoogleTagManager';

const GOOGLE_ANALYTICS_ID_V4 = process.env.NEXT_PUBLIC_GOOGLE_ANALYTICS_ID;

export function GoogleAnalytics({ children }: { children?: React.ReactNode }) {
  const currentRoute = usePathname();
  const [stylingVariant] = usePreference('variant', 'CssModules:Tailwind', 'CssModules');

  if (!GOOGLE_ANALYTICS_ID_V4) {
    return <React.Fragment>{children}</React.Fragment>;
  }

  return (
    <React.Fragment>
      <GoogleTagManager id={GOOGLE_ANALYTICS_ID_V4} />
      <GoogleAnalyticsProvider
        id={GOOGLE_ANALYTICS_ID_V4}
        productId="base-ui"
        productCategoryId="core"
        currentRoute={currentRoute}
        codeLanguage="ts"
        codeStylingVariant={stylingVariant}
        userLanguage="en"
      >
        {children}
      </GoogleAnalyticsProvider>
    </React.Fragment>
  );
}
