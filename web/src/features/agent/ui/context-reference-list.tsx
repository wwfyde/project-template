import { CircleDashed, FileText, Link2 } from 'lucide-react'

import type { AgentActionsCopy } from '../model/action-translations'
import type { ContextReference } from '../model/context'

export function ContextReferenceList({ items, copy }: { items: ContextReference[]; copy: AgentActionsCopy }) {
  return (
    <div className="mb-2 flex flex-col items-end gap-2">
      {items.map((reference) => {
        const Icon = reference.kind === 'link' ? Link2 : reference.kind === 'skill' ? CircleDashed : FileText
        const kind = reference.kind === 'text' ? copy.note : reference.kind === 'link' ? copy.link : copy.skill
        return (
          <details
            key={reference.id}
            className="max-w-full rounded-panel border border-border bg-background text-xs open:w-full"
          >
            <summary
              className="flex min-h-control cursor-pointer items-center gap-2 rounded-control px-3 py-2 text-muted-foreground outline-none hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring"
              aria-label={`${kind}: ${reference.title}`}
            >
              <Icon size={14} className="shrink-0" aria-hidden="true" />
              <span className="min-w-0 truncate font-medium text-foreground">{reference.title}</span>
              <span className="shrink-0 text-[10px]">{kind}</span>
            </summary>
            <div className="max-h-64 overflow-y-auto border-t border-border px-3 py-3 leading-6 whitespace-pre-wrap [overflow-wrap:anywhere]">
              {reference.kind === 'link' ? (
                <>
                  <a href={reference.url} target="_blank" rel="noreferrer" className="underline underline-offset-4">
                    {reference.url}
                  </a>
                  <p className="mt-2 text-muted-foreground">{copy.linkHint}</p>
                </>
              ) : reference.kind === 'text' ? (
                reference.text
              ) : (
                <>
                  <p className="font-medium">
                    {reference.title} · v{reference.version}
                  </p>
                  <p>{reference.description}</p>
                  <p className="mt-2 text-muted-foreground">{copy.skillHint}</p>
                </>
              )}
            </div>
          </details>
        )
      })}
    </div>
  )
}
