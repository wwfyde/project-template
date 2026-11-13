import { FileText, Folder } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import type { SkillTreeNode } from '../model/skill'
import './skills.css'

export type SkillTreeProps = {
  nodes: SkillTreeNode[]
  selectedPath?: string | null
  onSelect: (node: SkillTreeNode) => void
  label?: string
}

/** Native disclosures support keyboard expansion without simulating an ARIA tree widget. */
export function SkillTree({ nodes, selectedPath, onSelect, label }: SkillTreeProps) {
  const { t } = useTranslation('skills')
  if (!nodes.length) return <p className="p-3 text-sm text-muted-foreground">{t('emptyTree')}</p>
  return (
    <nav aria-label={label ?? t('treeLabel')} className="skill-tree">
      <SkillTreeBranch nodes={nodes} selectedPath={selectedPath} onSelect={onSelect} />
    </nav>
  )
}

function SkillTreeBranch({ nodes, selectedPath, onSelect }: SkillTreeProps) {
  return (
    <ul>
      {nodes.map((node) => (
        <li key={node.path}>
          {node.type === 'directory' ? (
            <details open>
              <summary title={node.path}>
                <span className="inline-flex min-w-0 items-center gap-2 align-middle">
                  <Folder size={15} className="shrink-0" aria-hidden="true" />
                  <span className="truncate">{node.name}</span>
                </span>
              </summary>
              <SkillTreeBranch nodes={node.children} selectedPath={selectedPath} onSelect={onSelect} />
            </details>
          ) : (
            <button
              type="button"
              title={node.path}
              aria-current={selectedPath === node.path ? 'true' : undefined}
              onClick={() => onSelect(node)}
            >
              <FileText size={15} className="shrink-0" aria-hidden="true" />
              <span className="truncate">{node.name}</span>
            </button>
          )}
        </li>
      ))}
    </ul>
  )
}
