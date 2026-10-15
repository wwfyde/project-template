import fs from 'fs/promises';
import os from 'os';
import path from 'path';
import { afterEach, expect, it } from 'vitest';
import { generateLlmsTxt } from './index.mjs';

const temporaryDirectories = [];

afterEach(async () => {
  await Promise.all(
    temporaryDirectories
      .splice(0)
      .map((directory) => fs.rm(directory, { recursive: true, force: true })),
  );
});

it('discovers custom sections and removes obsolete Markdown without deleting static assets', async () => {
  const temporaryDirectory = await fs.mkdtemp(path.join(os.tmpdir(), 'docs-mdx-llms-'));
  temporaryDirectories.push(temporaryDirectory);
  const sourceDir = path.join(temporaryDirectory, 'source');
  const outputDir = path.join(temporaryDirectory, 'output');
  const articleDirectory = path.join(sourceDir, 'my-guides', 'first-page');
  const previousOutputDirectory = path.join(outputDir, 'react', 'removed');
  await fs.mkdir(articleDirectory, { recursive: true });
  await fs.mkdir(previousOutputDirectory, { recursive: true });
  await fs.writeFile(path.join(sourceDir, 'page.mdx'), '# Docs\n\nRoot navigation.\n');
  await fs.writeFile(
    path.join(sourceDir, 'my-guides', 'page.mdx'),
    '# My guides\n\nSection navigation.\n',
  );
  await fs.writeFile(
    path.join(articleDirectory, 'page.mdx'),
    '# 写作指南：基础\n\n<Meta name="description" content="A project guide." />\n\n[This page](/react/my-guides/first-page)\n',
  );
  await fs.writeFile(path.join(previousOutputDirectory, 'old-page.md'), '# Obsolete article\n');
  await fs.writeFile(path.join(previousOutputDirectory, 'old-page.html'), '<p>Keep this asset</p>');
  const obsoleteDirectory = path.join(outputDir, 'react', 'obsolete', 'nested');
  await fs.mkdir(obsoleteDirectory, { recursive: true });
  await fs.writeFile(path.join(obsoleteDirectory, 'old.md'), '# Removed\n');

  await generateLlmsTxt({ sourceDir, outputDir, baseUrl: 'https://docs.example.com' });

  const llms = await fs.readFile(path.join(outputDir, 'llms.txt'), 'utf-8');
  const full = await fs.readFile(path.join(outputDir, 'llms-full.txt'), 'utf-8');
  const index = await fs.readFile(path.join(outputDir, 'index.md'), 'utf-8');
  const article = await fs.readFile(
    path.join(outputDir, 'react', 'my-guides', 'first-page.md'),
    'utf-8',
  );

  expect(llms).toContain('# Docs');
  expect(llms).toContain('## My guides');
  expect(llms).toContain(
    '[写作指南：基础](https://docs.example.com/react/my-guides/first-page.md)',
  );
  expect(llms).not.toContain('Base UI');
  expect(llms).not.toContain('removed');
  expect(full).toContain('### 写作指南：基础');
  expect(full).toContain('[This page](#写作指南基础)');
  expect(full).not.toContain('Section navigation');
  expect(index).toContain('[写作指南：基础](./react/my-guides/first-page.md)');
  expect(article).toContain('[This page](/react/my-guides/first-page.md)');
  await expect(fs.access(path.join(previousOutputDirectory, 'old-page.md'))).rejects.toThrow();
  await expect(fs.access(path.join(outputDir, 'react', 'obsolete'))).rejects.toThrow();
  expect(await fs.readFile(path.join(previousOutputDirectory, 'old-page.html'), 'utf-8')).toBe(
    '<p>Keep this asset</p>',
  );

  // Renaming an article updates every index and removes its previous export.
  await fs.rename(articleDirectory, path.join(sourceDir, 'my-guides', 'renamed-page'));
  await generateLlmsTxt({ sourceDir, outputDir });
  const updatedIndex = await fs.readFile(path.join(outputDir, 'index.md'), 'utf-8');
  expect(updatedIndex).toContain('./react/my-guides/renamed-page.md');
  expect(updatedIndex).not.toContain('./react/my-guides/first-page.md');
  await expect(
    fs.access(path.join(outputDir, 'react', 'my-guides', 'first-page.md')),
  ).rejects.toThrow();
});
