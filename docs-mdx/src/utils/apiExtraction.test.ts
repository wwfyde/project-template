import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { loadServerTypesMeta } from '@mui/internal-docs-infra/pipeline/loadServerTypesMeta';
import { projectApiDeclarations } from '../../scripts/apiTypes/projectDeclarations.mjs';

describe('API extraction', () => {
  it('extracts Checkbox props and state from the installed package declarations', async () => {
    const rootContext = resolve(import.meta.dirname, '../..');
    const require = createRequire(import.meta.url);
    const packageRoot = dirname(require.resolve('@base-ui/react/package.json'));
    // Exercise the extractor itself, independently of checked-in types.md and snapshots.
    const projection = await projectApiDeclarations({
      rootContext,
      resourcePath: resolve(rootContext, 'src/utils/fixtures/checkbox/types.ts'),
      variants: { Checkbox: '@base-ui/react/checkbox' },
    });
    const metadata = await loadServerTypesMeta({
      rootContext,
      typesMarkdownPath: resolve(rootContext, 'src/utils/fixtures/checkbox/types.md'),
      variants: projection.variants,
      watchSourceDirectly: false,
    });

    expect(metadata.exports.Root?.type).toMatchObject({
      type: 'component',
      data: {
        props: {
          checked: { typeText: 'boolean | undefined' },
          defaultChecked: { typeText: 'boolean | undefined' },
          indeterminate: { typeText: 'boolean | undefined' },
          disabled: { typeText: 'boolean | undefined' },
          onCheckedChange: {
            typeText: expect.stringContaining('checked: boolean'),
          },
          className: expect.any(Object),
          render: expect.any(Object),
          style: expect.any(Object),
        },
      },
    });
    expect(metadata.exports.Root?.type).not.toHaveProperty('data.props.onClick');
    expect(metadata.exports.Root?.type).not.toHaveProperty('data.props.aria-label');
    expect(
      metadata.allDependencies.map(
        (dependency) => projection.sourceByProjection.get(dependency) ?? dependency,
      ),
    ).toContain(resolve(packageRoot, 'checkbox/index.d.mts'));
    expect(projection.dependencies).toContain(resolve(packageRoot, 'package.json'));
    expect(packageRoot).toMatch(/[/\\]node_modules[/\\]/);
    expect(metadata.allDependencies.some((dependency) => dependency.includes('/vendor/'))).toBe(
      false,
    );
    expect(metadata.exports.Root?.additionalTypes).toContainEqual(
      expect.objectContaining({
        name: 'Checkbox.Root.State',
        data: expect.objectContaining({
          formattedCode: expect.stringContaining('checked: boolean'),
        }),
      }),
    );
    expect(
      [...projection.sourceByProjection.values()].every((dependency) =>
        /[/\\]node_modules[/\\]@base-ui[/\\](react|utils)[/\\]/.test(dependency),
      ),
    ).toBe(true);
  }, 30_000);
});
