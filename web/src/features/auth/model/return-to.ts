export function normalizeReturnTo(value: string | undefined, origin = window.location.origin): string {
  if (!value || /[\\\p{Cc}\s]/u.test(value)) {
    return '/'
  }

  try {
    const url = new URL(value, origin)
    if (url.origin !== origin || url.username || url.password) {
      return '/'
    }
    // Keep redirects away from login and API endpoints, which can otherwise
    // create a redirect loop or navigate directly into an OAuth callback.
    const pathname = decodeURIComponent(url.pathname)
    if (
      !pathname.startsWith('/') ||
      pathname.startsWith('//') ||
      /[\\\p{Cc}]/u.test(pathname) ||
      /^\/(?:api|login)(?:\/|$)/i.test(pathname)
    ) {
      return '/'
    }
    return `${url.pathname}${url.search}${url.hash}`
  } catch {
    return '/'
  }
}
