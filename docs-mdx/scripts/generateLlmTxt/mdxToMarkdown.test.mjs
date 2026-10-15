import { describe, it, expect } from 'vitest';
import fs from 'fs';
import path from 'path';
import { mdxToMarkdown } from './mdxToMarkdown.mjs';

describe('mdxToMarkdown', () => {
  // Fixtures preserve the original demo and API parsing coverage independently
  // of the articles maintained in the documentation site.
  it('should transform Accordion MDX content to markdown with metadata', async () => {
    // Read the independent Accordion MDX fixture
    const accordionMdxPath = path.resolve(import.meta.dirname, './fixtures/accordion/page.mdx');
    const accordionMdxContent = fs.readFileSync(accordionMdxPath, 'utf-8');

    // Transform the MDX content
    const result = await mdxToMarkdown(accordionMdxContent, accordionMdxPath);

    // Verify the result structure
    expect(result).toBeTypeOf('object');
    expect(result).toHaveProperty('markdown');
    expect(result).toHaveProperty('title');
    expect(result).toHaveProperty('subtitle');
    expect(result).toHaveProperty('description');

    // Verify extracted metadata
    expect(result.title).toBe('Accordion');
    expect(result.subtitle).toBe('A set of collapsible panels with headings.');
    expect(result.description).toBe(
      'A high-quality, unstyled React accordion component that displays a set of collapsible panels with headings.',
    );

    // Snapshot test the complete result
    expect(result.markdown).toMatchSnapshot();
  });

  // A snapshot test for utility MDX content.
  // Serves as an integration test for the markdown generation of utils docs.
  it('should transform Direction Provider MDX content to markdown with metadata', async () => {
    // Read the independent Direction Provider MDX fixture
    const directionProviderMdxPath = path.resolve(
      import.meta.dirname,
      './fixtures/direction-provider/page.mdx',
    );
    const directionProviderMdxContent = fs.readFileSync(directionProviderMdxPath, 'utf-8');

    // Transform the MDX content
    const result = await mdxToMarkdown(directionProviderMdxContent, directionProviderMdxPath);

    // Verify the result structure
    expect(result).toBeTypeOf('object');
    expect(result).toHaveProperty('markdown');
    expect(result).toHaveProperty('title');
    expect(result).toHaveProperty('subtitle');
    expect(result).toHaveProperty('description');

    // Verify extracted metadata
    expect(result.title).toBe('Direction Provider');
    expect(result.subtitle).toBe('Enables RTL behavior for Base UI components.');
    expect(result.description).toBe(
      'A direction provider component that enables RTL behavior for Base UI components.',
    );

    // Snapshot test the complete result
    expect(result.markdown).toMatchSnapshot();
  });
});
