// Keep CSS imports first to ensure CSS layer order is correct
import 'docs-mdx/src/css/index.css';
import './layout.css';

import * as React from 'react';
import type { Metadata, Viewport } from 'next/types';
import { GoogleAnalytics } from 'docs-mdx/src/components/GoogleAnalytics';
import { DocsProviders } from 'docs-mdx/src/components/DocsProviders';
import * as SideNav from 'docs-mdx/src/components/SideNav';
import * as QuickNav from 'docs-mdx/src/components/QuickNav/QuickNav';
import { Header } from 'docs-mdx/src/components/Header';
import { MAIN_CONTENT_ID } from 'docs-mdx/src/components/SkipNav';
import { sitemap } from 'docs-mdx/src/app/sitemap';
import { MarkdownIcon } from 'docs-mdx/src/icons/MarkdownIcon';
import { getDisplayTitle } from 'docs-mdx/src/utils/getDisplayTitle';
import { getSitemapPageInfo, isSitemapPageVisible } from 'docs-mdx/src/utils/sitemapPage';
import { siteConfig } from 'docs-mdx/src/site.config.mjs';

export default function Layout({ children }: React.PropsWithChildren) {
  return (
    // Use suppressHydrationWarning to avoid https://github.com/react/react/issues/24430
    <html lang="zh-CN">
      <head>
        <link
          rel="preload"
          href="/fonts/die-grotesk-a-regular.woff2"
          as="font"
          type="font/woff2"
          crossOrigin="anonymous"
        />
        <link
          rel="preload"
          href="/fonts/die-grotesk-a-bold.woff2"
          as="font"
          type="font/woff2"
          crossOrigin="anonymous"
        />
        <link
          rel="preload"
          href="/fonts/die-grotesk-b-bold.woff2"
          as="font"
          type="font/woff2"
          crossOrigin="anonymous"
        />
        <link
          rel="preload"
          href="/fonts/paper-mono.woff2"
          as="font"
          type="font/woff2"
          crossOrigin="anonymous"
        />
      </head>
      <body suppressHydrationWarning>
        <GoogleAnalytics>
          <DocsProviders>
            <div className="RootLayout">
              <div className="RootLayoutContainer">
                <div className="RootLayoutContent">
                  <div className="ContentLayoutRoot">
                    <Header />
                    <SideNav.Root>
                      {sitemap &&
                        Object.entries(sitemap.data).map(([name, section]) => (
                          <SideNav.Section key={name}>
                            <SideNav.Heading>{name}</SideNav.Heading>
                            <SideNav.List>
                              {section.pages.filter(isSitemapPageVisible).map((page) => {
                                const pageInfo = getSitemapPageInfo(section, page);

                                return (
                                  <SideNav.Item
                                    key={page.title}
                                    href={pageInfo.href}
                                    external={pageInfo.external}
                                  >
                                    {getDisplayTitle(page.title)}
                                    {pageInfo.badges.map((badge) => (
                                      <SideNav.Badge key={badge}>{badge}</SideNav.Badge>
                                    ))}
                                  </SideNav.Item>
                                );
                              })}
                            </SideNav.List>
                          </SideNav.Section>
                        ))}
                      <SideNav.Separator />
                      <SideNav.Section>
                        <SideNav.Heading>文档工具</SideNav.Heading>
                        <SideNav.List>
                          <SideNav.Item href="/llms.txt" icon={<MarkdownIcon />} external>
                            llms.txt
                          </SideNav.Item>
                        </SideNav.List>
                      </SideNav.Section>
                    </SideNav.Root>

                    <main className="ContentLayoutMain" id={MAIN_CONTENT_ID}>
                      <QuickNav.Container>{children}</QuickNav.Container>
                    </main>
                  </div>
                </div>
              </div>
            </div>
          </DocsProviders>
        </GoogleAnalytics>
      </body>
    </html>
  );
}

export const metadata: Metadata = {
  // MDX pages override these defaults with their <h1> and <Subtitle>.
  title: siteConfig.name,
  description: siteConfig.description,
  openGraph: {
    // 'article' is more semantically correct for documentation pages and
    // unlocks article-specific OG properties.
    type: 'article',
    locale: 'zh_CN',
    siteName: siteConfig.name,
    description: siteConfig.description,
    url: './',
    ttl: 604800,
  },
  metadataBase: new URL(siteConfig.baseUrl),
  alternates: { canonical: './' },
  icons: { icon: '/favicon.svg' },
};

export const viewport: Viewport = {
  initialScale: 1,
  width: 'device-width',
  themeColor: [
    // Safari header background: match the page background (--color-content)
    {
      media: '(prefers-color-scheme: light)',
      color: 'white',
    },
    {
      media: '(prefers-color-scheme: dark)',
      color: 'black',
    },
  ],
};
