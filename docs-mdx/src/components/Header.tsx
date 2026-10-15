import NextLink from 'next/link';
import { siteConfig } from '../site.config.mjs';

import { Logo } from './Logo';
import { SearchControls } from './SearchControls';
import { SkipNav } from './SkipNav';
import './Header.css';

export const HEADER_HEIGHT_DESKTOP = 64;

export function Header() {
  return (
    <header className="Header">
      <div className="HeaderInner">
        <SkipNav>Skip to contents</SkipNav>
        <NextLink
          href={siteConfig.entryPath}
          className="HeaderLogoLink"
          aria-label={`${siteConfig.name} 文档首页`}
        >
          <Logo aria-hidden="true" />
          <span>{siteConfig.name}</span>
        </NextLink>
        <div className="HeaderSearch">
          <SearchControls
            desktopTriggerClassName="HeaderSearchDesktopTrigger"
            mobileTriggerClassName="HeaderSearchMobileTrigger"
          />
        </div>
      </div>
    </header>
  );
}
