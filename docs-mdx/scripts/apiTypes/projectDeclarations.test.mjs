import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, it } from 'vitest';
import { projectApiDeclarations } from './projectDeclarations.mjs';

it('refreshes projected declarations after source edits and package upgrades', async () => {
  const rootContext = await fs.realpath(
    await fs.mkdtemp(path.join(os.tmpdir(), 'docs-api-declarations-')),
  );
  const packageRoot = path.join(rootContext, 'node_modules/@base-ui/react');
  const declarationPath = path.join(packageRoot, 'index.d.mts');
  const manifestPath = path.join(packageRoot, 'package.json');
  const manifest = {
    name: '@base-ui/react',
    version: '1.0.0',
    exports: { '.': { import: { types: './index.d.mts' } } },
  };
  const options = {
    rootContext,
    resourcePath: path.join(rootContext, 'types.ts'),
    variants: { Widget: '@base-ui/react' },
  };

  try {
    await fs.mkdir(packageRoot, { recursive: true });
    await fs.writeFile(manifestPath, JSON.stringify(manifest));
    await fs.writeFile(declarationPath, 'export interface WidgetState { active: boolean }');
    const first = await projectApiDeclarations(options);
    expect(first.dependencies).toEqual(expect.arrayContaining([declarationPath, manifestPath]));
    expect([...first.sourceByProjection.values()]).toContain(declarationPath);

    const repeated = await projectApiDeclarations(options);
    expect(repeated.variants).toEqual(first.variants);

    await fs.writeFile(
      declarationPath,
      'export interface WidgetState { active: boolean; disabled: boolean }',
    );
    const edited = await projectApiDeclarations(options);
    expect(edited.variants.Widget).not.toBe(first.variants.Widget);
    expect(await fs.readFile(`${fileURLToPath(edited.variants.Widget)}.d.ts`, 'utf8')).toContain(
      'disabled: boolean',
    );

    await fs.writeFile(manifestPath, JSON.stringify({ ...manifest, version: '2.0.0' }));
    const upgraded = await projectApiDeclarations(options);
    expect(upgraded.variants.Widget).not.toBe(edited.variants.Widget);
  } finally {
    await fs.rm(rootContext, { recursive: true, force: true });
  }
});
