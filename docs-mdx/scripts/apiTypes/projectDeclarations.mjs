import { createHash, randomUUID } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import ts from 'typescript';

const compilerOptions = {
  module: ts.ModuleKind.ESNext,
  moduleResolution: ts.ModuleResolutionKind.Bundler,
};

function documentedPackage(filePath) {
  const normalized = filePath.replaceAll('\\', '/');
  const packagePath = normalized.split('/node_modules/').at(-1);
  const match = packagePath.match(/^(@base-ui\/(?:react|utils))\/(.+\.d\.[cm]?ts)$/);
  if (!match || packagePath === normalized) {
    return undefined;
  }
  return {
    name: match[1],
    root: filePath.slice(0, filePath.length - match[2].length - 1),
    relativePath: match[2],
  };
}

function moduleSpecifiers(source, filePath) {
  const sourceFile = ts.createSourceFile(filePath, source, ts.ScriptTarget.Latest, true);
  const specifiers = [];
  function visit(node) {
    const literal =
      (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier
        ? node.moduleSpecifier
        : ts.isImportTypeNode(node) && ts.isLiteralTypeNode(node.argument)
          ? node.argument.literal
          : ts.isExternalModuleReference(node)
            ? node.expression
            : undefined;
    if (literal && ts.isStringLiteral(literal)) {
      specifiers.push({
        value: literal.text,
        start: literal.getStart(sourceFile),
        end: literal.end,
      });
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return specifiers;
}

function replaceSpecifiers(source, replacements) {
  for (const replacement of replacements.toSorted((a, b) => b.start - a.start)) {
    source =
      source.slice(0, replacement.start) +
      JSON.stringify(replacement.value) +
      source.slice(replacement.end);
  }
  return source;
}

async function writeCacheFile(filePath, content) {
  try {
    await fs.access(filePath);
    return;
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  const temporaryPath = `${filePath}.${randomUUID()}.tmp`;
  try {
    await fs.writeFile(temporaryPath, content);
    await fs.rename(temporaryPath, filePath);
  } finally {
    await fs.rm(temporaryPath, { force: true });
  }
}

/**
 * Project only reachable Base UI declarations into an ignored build cache.
 * The extractor treats node_modules declarations as external; local declaration
 * inputs use its standard API without changing its dependency filtering policy.
 * Other libraries keep their original paths and remain external to the docs.
 */
export async function projectApiDeclarations({ rootContext, resourcePath, variants }) {
  const resolutionCache = ts.createModuleResolutionCache(
    rootContext,
    (fileName) => fileName,
    compilerOptions,
  );
  const resolveModule = (specifier, containingFile) =>
    ts.resolveModuleName(
      specifier,
      containingFile,
      compilerOptions,
      ts.sys,
      resolutionCache,
      undefined,
      ts.ModuleKind.ESNext,
    ).resolvedModule?.resolvedFileName;
  const files = new Map();
  const manifests = new Map();
  const resolvedVariants = new Map();

  function enqueue(filePath) {
    const owner = documentedPackage(filePath);
    if (owner && !files.has(filePath)) {
      files.set(filePath, { owner });
    }
    return owner;
  }

  for (const [name, specifier] of Object.entries(variants)) {
    if (!/^@base-ui\/(?:react|utils)(?:\/|$)/.test(specifier)) continue;
    const filePath = resolveModule(specifier, resourcePath);
    if (!filePath || !enqueue(filePath)) {
      throw new Error(
        `Cannot resolve installed declarations for ${specifier} from ${resourcePath}`,
      );
    }
    resolvedVariants.set(name, filePath);
  }

  // Map iteration includes newly discovered entries, so cycles are visited once.
  for (const [filePath, file] of files) {
    const manifestPath = path.join(file.owner.root, 'package.json');
    if (!manifests.has(manifestPath)) {
      manifests.set(manifestPath, await fs.readFile(manifestPath, 'utf8'));
    }
    file.source = await fs.readFile(filePath, 'utf8');
    file.imports = moduleSpecifiers(file.source, filePath).map((specifier) => {
      const dependency = resolveModule(specifier.value, filePath);
      if (dependency) enqueue(dependency);
      return { ...specifier, dependency };
    });
  }

  // A changed declaration or installed package version gets a fresh snapshot,
  // invalidating both the upstream metadata cache and TypeScript's program cache.
  const hash = createHash('sha256').update('api-declarations-v2');
  for (const [filePath, file] of [...files].sort(([a], [b]) => a.localeCompare(b))) {
    hash.update(filePath).update('\0').update(file.source).update('\0');
    for (const specifier of file.imports)
      hash.update(specifier.dependency ?? specifier.value).update('\0');
  }
  for (const [manifestPath, content] of [...manifests].sort(([a], [b]) => a.localeCompare(b))) {
    hash.update(manifestPath).update('\0').update(content).update('\0');
  }
  const cacheRoot = path.join(
    rootContext,
    '.cache/api-declarations',
    hash.digest('hex').slice(0, 20),
  );
  const projectedPackages = new Map();
  const projectedFiles = new Map(
    [...files].map(([filePath, { owner }]) => {
      const packageId = createHash('sha256').update(owner.root).digest('hex').slice(0, 8);
      const packageType = filePath.endsWith('.d.mts')
        ? 'module'
        : filePath.endsWith('.d.cts')
          ? 'commonjs'
          : (JSON.parse(manifests.get(path.join(owner.root, 'package.json'))).type ?? 'commonjs');
      const packageDirectory = path.join(
        cacheRoot,
        `${owner.name.replaceAll('/', '-')}-${packageId}`,
        packageType,
      );
      projectedPackages.set(packageDirectory, packageType);
      // The upstream local-file resolver supports .d.ts but not .d.mts/.d.cts.
      // Preserve module semantics with package.json and distinct declaration names.
      const relativePath = owner.relativePath.replace(/\.d\.([cm])ts$/, '.$1ts.d.ts');
      return [filePath, path.join(packageDirectory, relativePath)];
    }),
  );

  await Promise.all(
    [...projectedPackages].map(([directory, type]) =>
      writeCacheFile(path.join(directory, 'package.json'), JSON.stringify({ type })),
    ),
  );
  await Promise.all(
    [...files].map(async ([filePath, file]) => {
      const targetPath = projectedFiles.get(filePath);
      const replacements = file.imports
        .filter((specifier) => specifier.dependency)
        .map((specifier) => {
          const dependencyPath = projectedFiles.get(specifier.dependency) ?? specifier.dependency;
          let relativePath = path
            .relative(path.dirname(targetPath), dependencyPath)
            .replaceAll('\\', '/');
          if (!relativePath.startsWith('.')) relativePath = `./${relativePath}`;
          return { ...specifier, value: relativePath };
        });
      await writeCacheFile(targetPath, replaceSpecifiers(file.source, replacements));
    }),
  );

  return {
    variants: Object.fromEntries(
      Object.entries(variants).map(([name, specifier]) => [
        name,
        // Its local variant resolver expects an extensionless path.
        resolvedVariants.has(name)
          ? pathToFileURL(projectedFiles.get(resolvedVariants.get(name)).replace(/\.d\.ts$/, ''))
              .href
          : specifier,
      ]),
    ),
    sourceByProjection: new Map(
      [...projectedFiles].map(([source, projected]) => [projected, source]),
    ),
    dependencies: [...files.keys(), ...manifests.keys()],
  };
}

/** Prepare the loader input while keeping normal package imports in authored files. */
export async function projectTypesSource(source, resourcePath, rootContext) {
  const imports = moduleSpecifiers(source, resourcePath).filter(({ value }) =>
    /^@base-ui\/(?:react|utils)(?:\/|$)/.test(value),
  );
  const projection = await projectApiDeclarations({
    rootContext,
    resourcePath,
    variants: Object.fromEntries(imports.map(({ value }) => [value, value])),
  });
  const originalSpecifiers = new Map(
    Object.entries(projection.variants).map(([original, projected]) => [projected, original]),
  );
  return {
    ...projection,
    restoreImports(output) {
      return replaceSpecifiers(
        output,
        moduleSpecifiers(output, resourcePath)
          .filter(({ value }) => originalSpecifiers.has(value))
          .map((specifier) => ({ ...specifier, value: originalSpecifiers.get(specifier.value) })),
      );
    },
    source: replaceSpecifiers(
      source,
      imports.map((specifier) => ({
        ...specifier,
        value: projection.variants[specifier.value],
      })),
    ),
  };
}
