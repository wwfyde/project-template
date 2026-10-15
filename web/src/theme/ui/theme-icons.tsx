import type { SVGProps } from 'react'

type PreviewIconProps = SVGProps<SVGSVGElement>

const commonProps = {
  viewBox: '0 0 80 52',
  fill: 'none',
  xmlns: 'http://www.w3.org/2000/svg',
} as const

function PreviewShell({ children, ...props }: PreviewIconProps) {
  return (
    <svg {...commonProps} {...props}>
      {children}
    </svg>
  )
}

function DashboardMarks() {
  return (
    <>
      <circle cx="11" cy="10" r="4" fill="currentColor" opacity="0.8" />
      <rect x="18" y="7" width="12" height="3" rx="1.5" fill="currentColor" opacity="0.8" />
      <rect x="18" y="13" width="9" height="2" rx="1" fill="currentColor" opacity="0.5" />
      <rect x="7" y="23" width="19" height="3" rx="1.5" fill="currentColor" opacity="0.7" />
      <rect x="7" y="30" width="16" height="3" rx="1.5" fill="currentColor" opacity="0.5" />
      <rect x="38" y="29" width="31" height="15" rx="3" fill="currentColor" opacity="0.22" />
      <rect x="39" y="16" width="5" height="8" rx="1" fill="currentColor" opacity="0.35" />
      <rect x="47" y="12" width="5" height="12" rx="1" fill="currentColor" opacity="0.5" />
      <rect x="55" y="7" width="5" height="17" rx="1" fill="currentColor" opacity="0.7" />
      <circle cx="68" cy="15" r="8" fill="currentColor" opacity="0.28" />
      <path d="M68 15 73 8A8 8 0 0 1 76 15Z" fill="currentColor" opacity="0.65" />
    </>
  )
}

export function SystemThemeIcon(props: PreviewIconProps) {
  return (
    <PreviewShell {...props}>
      <rect width="80" height="52" rx="6" fill="var(--preview-dark, #262626)" />
      <path d="M40 0H74a6 6 0 0 1 6 6v40a6 6 0 0 1-6 6H40Z" fill="var(--preview-light, #f4f4f5)" />
      <g color="var(--preview-muted, #a1a1aa)">
        <DashboardMarks />
      </g>
    </PreviewShell>
  )
}

export function LightThemeIcon(props: PreviewIconProps) {
  return (
    <PreviewShell {...props}>
      <rect width="80" height="52" rx="6" fill="#f4f4f5" />
      <rect width="24" height="52" rx="6" fill="#e4e4e7" />
      <g color="#a1a1aa">
        <DashboardMarks />
      </g>
    </PreviewShell>
  )
}

export function DarkThemeIcon(props: PreviewIconProps) {
  return (
    <PreviewShell {...props}>
      <rect width="80" height="52" rx="6" fill="#0f172a" />
      <rect width="24" height="52" rx="6" fill="#172554" />
      <g color="#60a5fa">
        <DashboardMarks />
      </g>
    </PreviewShell>
  )
}
