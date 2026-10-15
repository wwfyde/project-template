import { pathToFileURL } from "node:url";
import {
  parseCreateFactoryCall,
  replacePrecomputeValue,
} from "@mui/internal-docs-infra/pipeline/parseCreateFactoryCall";
import { rewriteImportsToNull } from "@mui/internal-docs-infra/pipeline/loaderUtils";
import { createSitemapSchema } from "@mui/internal-docs-infra/pipeline/loadServerSitemap";
import { loadDocumentIndex } from "./loadDocumentIndex.mjs";

/** Precompute with the upstream factory tools and the source-aware index reader. */
export default function loadPrecomputedSitemap(source) {
  const callback = this.async();
  this.cacheable();
  const run = async () => {
    const factory = await parseCreateFactoryCall(
      source,
      pathToFileURL(this.resourcePath).href,
    );
    if (!factory?.variants || factory.options.skipPrecompute) return source;
    const entries = await Promise.all(
      Object.entries(factory.variants).map(async ([name, filePath]) => [
        name,
        await loadDocumentIndex(filePath, {
          rootContext: this.rootContext,
          addDependency: (dependency) => this.addDependency(dependency),
        }),
      ]),
    );
    const precompute = {
      schema: createSitemapSchema(),
      data: Object.fromEntries(entries.filter(([, index]) => index)),
    };
    const result = replacePrecomputeValue(source, precompute, factory);
    const imports = Object.fromEntries(
      Object.entries(factory.importsAndComments?.relative ?? {}).filter(
        ([importPath]) => importPath.endsWith(".mdx"),
      ),
    );
    return rewriteImportsToNull(result, new Set(Object.keys(imports)), imports);
  };
  run().then(
    (result) => callback(null, result),
    (error) => callback(error),
  );
}
