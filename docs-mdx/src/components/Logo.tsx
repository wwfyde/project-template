import * as React from 'react';

export function Logo(props: React.ComponentProps<'svg'>) {
  return (
    <svg
      width="20"
      height="24"
      viewBox="0 0 20 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="M4 2h8l5 5v13a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Z" />
      <path d="M12 2v5h5M6 12h7M6 16h7" />
    </svg>
  );
}
