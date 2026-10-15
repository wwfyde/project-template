import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { expect, it } from 'vitest';
import loadPrecomputedTypes from './loadPrecomputedTypes.mjs';

it('precomputes API data, removes declaration imports, and watches installed sources', async () => {
  const rootContext = path.resolve(import.meta.dirname, '../..');
  await fs.mkdir(path.join(rootContext, '.cache'), { recursive: true });
  const directory = await fs.mkdtemp(path.join(rootContext, '.cache/api-loader-test-'));
  const resourcePath = path.join(directory, 'types.ts');
  const source = `import { Checkbox } from '@base-ui/react/checkbox';
import { createMultipleTypes } from 'docs-mdx/src/utils/createTypes';
export { useTimeout } from '@base-ui/utils/useTimeout';
export const { types } = createMultipleTypes(import.meta.url, Checkbox);
`;
  const dependencies = new Set();
  try {
    await fs.writeFile(resourcePath, source);
    const compiled = await new Promise((resolve, reject) => {
      loadPrecomputedTypes.call(
        {
          rootContext,
          resourcePath,
          async: () => (error, output) => (error ? reject(error) : resolve(output)),
          cacheable() {},
          getOptions: () => ({}),
          addDependency: (dependency) => dependencies.add(dependency),
        },
        source,
      );
    });
    expect(compiled).toContain('precompute');
    expect(compiled).not.toContain('@base-ui/react/checkbox');
    expect(compiled).toContain('@base-ui/utils/useTimeout');
    expect(compiled).not.toContain('.cache/api-declarations');
    const packageRoot = path.dirname(
      createRequire(import.meta.url).resolve('@base-ui/react/package.json'),
    );
    expect(dependencies).toContain(path.join(packageRoot, 'checkbox/index.d.mts'));
    expect(dependencies).toContain(path.join(packageRoot, 'package.json'));
    const markdown = await fs.readFile(path.join(directory, 'types.md'), 'utf8');
    expect(markdown).toContain('onCheckedChange');
    expect(markdown).toContain('Checkbox.Root.State');
  } finally {
    await fs.rm(directory, { recursive: true, force: true });
  }
}, 30_000);

it.each([
  [
    'skipped',
    'export const { types } = createMultipleTypes(import.meta.url, Checkbox, { skipPrecompute: true });',
  ],
  ['absent', 'export { Checkbox };'],
])('keeps package imports when precomputation is %s', async (_, statement) => {
  const rootContext = path.resolve(import.meta.dirname, '../..');
  const source = `import { Checkbox } from '@base-ui/react/checkbox';
import { createMultipleTypes } from 'docs-mdx/src/utils/createTypes';
${statement}
`;
  const compiled = await new Promise((resolve, reject) => {
    loadPrecomputedTypes.call(
      {
        rootContext,
        resourcePath: path.join(rootContext, '.cache/skipped-types.ts'),
        async: () => (error, output) => (error ? reject(error) : resolve(output)),
        cacheable() {},
        getOptions: () => ({}),
        addDependency() {},
      },
      source,
    );
  });
  expect(compiled).toContain('@base-ui/react/checkbox');
  expect(compiled).not.toContain('file://');
  expect(compiled).not.toContain('.cache/api-declarations');
});
