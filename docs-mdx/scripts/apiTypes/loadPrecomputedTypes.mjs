import upstreamLoader from '@mui/internal-docs-infra/pipeline/loadPrecomputedTypes';
import { projectTypesSource } from './projectDeclarations.mjs';

/** Build API tables from installed declarations without patching dependencies. */
export default function loadPrecomputedTypes(source) {
  const callback = this.async();
  projectTypesSource(source, this.resourcePath, this.rootContext || process.cwd())
    .then((projection) => {
      // Watch the installed files, not just immutable cache inputs. Package
      // manifest changes also invalidate exports resolution after an upgrade.
      projection.dependencies.forEach((dependency) => this.addDependency(dependency));
      const context = Object.create(this);
      // Upstream removes imports used by the factory. Restore any remaining
      // imports (including skipPrecompute) so declarations never enter bundles.
      context.async =
        () =>
        (error, output, ...rest) =>
          callback(
            error,
            typeof output === 'string' ? projection.restoreImports(output) : output,
            ...rest,
          );
      context.addDependency = (dependency) => {
        this.addDependency(projection.sourceByProjection.get(dependency) ?? dependency);
      };
      return upstreamLoader.call(context, projection.source);
    })
    .catch((error) => callback(error));
}
