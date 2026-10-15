'use client';
import * as React from 'react';
import type { Sitemap } from '@mui/internal-docs-infra/useSearch/types';
import * as MobileNav from './MobileNav';
import { MarkdownIcon } from '../icons/MarkdownIcon';
import { getDisplayTitle } from '../utils/getDisplayTitle';
import { getSitemapPageInfo, isSitemapPageVisible } from '../utils/sitemapPage';

interface MobileNavContentProps {
  sitemap: Sitemap | null;
}

export function MobileNavContent({ sitemap }: MobileNavContentProps) {
  if (!sitemap) {
    return null;
  }

  return (
    <React.Fragment>
      {Object.entries(sitemap.data).map(([name, section]) => (
        <MobileNav.Section key={name}>
          <MobileNav.Heading>{name}</MobileNav.Heading>
          <MobileNav.List>
            {section.pages.filter(isSitemapPageVisible).map((page) => {
              const pageInfo = getSitemapPageInfo(section, page);

              return (
                <MobileNav.Item key={page.title} href={pageInfo.href} external={pageInfo.external}>
                  <span className="MobileNavLinkText">{getDisplayTitle(page.title)}</span>
                  {pageInfo.badges.map((badge) => (
                    <MobileNav.Badge key={badge}>{badge}</MobileNav.Badge>
                  ))}
                </MobileNav.Item>
              );
            })}
          </MobileNav.List>
        </MobileNav.Section>
      ))}
      <MobileNav.Section>
        <MobileNav.Heading>文档工具</MobileNav.Heading>
        <MobileNav.List>
          <MobileNav.Item href="/llms.txt" external>
            <MarkdownIcon />
            <span className="MobileNavLinkText">llms.txt</span>
          </MobileNav.Item>
        </MobileNav.List>
      </MobileNav.Section>
    </React.Fragment>
  );
}
