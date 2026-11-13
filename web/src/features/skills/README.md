# Skills components

`/skills` provides authenticated skill and version management. `createSkillClient()` uses the existing `Auth.authenticatedRequest`, including session cookies and CSRF protection. Downloads use same-origin content endpoints. No skill is uploaded to OpenAI.

The module exports:

- `SkillTree`: presentational nested file list with native keyboard-accessible directory disclosures; accepts `nodes`, `selectedPath`, and `onSelect`.
- `SkillFilePreview`: presentational text, binary, loading, error and truncation states; accepts a `SkillFileData` response. Markdown, HTML and SVG are always escaped source text.
- `SkillPreview`: loads a version's tree, selects `SKILL.md`, and fetches files on demand. Requests are cancelled when the target changes. The concrete version returned by the tree endpoint pins subsequent file reads.
- `SkillsPage`: complete list, upload and version management interface.

Components use the application's `I18nextProvider` with the `skills` namespace and the shared CSS theme variables. Styles are imported by the components. Example inside an authenticated view:

```tsx
import { useMemo } from 'react'
import { useAuth } from '../auth'
import { createSkillClient, SkillPreview } from '../skills'

function Preview({ skillId, version }: { skillId: string; version: string }) {
  const { user, authenticatedRequest } = useAuth()
  const client = useMemo(() => createSkillClient({ authenticatedRequest }), [authenticatedRequest])
  return (
    <SkillPreview
      key={`${user?.account_id}:${user?.id}`}
      client={client}
      skillId={skillId}
      version={version}
    />
  )
}
```

Use an account/user key when embedding previews in a view that survives account changes. This discards previous account data immediately; the server remains responsible for enforcing ownership. For custom data sources, pass any object implementing the `tree` and `file` methods of `SkillClient`, or use the presentational components directly.

Directory uploads preserve `File.webkitRelativePath` in repeated `files[]` multipart fields; ZIP uploads use `files`. Uploading a new version leaves the default unchanged. The preview endpoints are local extensions; the remaining client methods follow the OpenAI Skills resource layout under the application's `/api` prefix.

Validation:

```bash
pnpm --filter web test
pnpm --filter web check-types
pnpm --filter web build
```
