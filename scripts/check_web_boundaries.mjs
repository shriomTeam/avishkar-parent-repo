import { readdirSync, readFileSync } from "node:fs";
import { resolve, relative, dirname } from "node:path";
const root = process.cwd();
function files(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    if (["node_modules", ".next", "test-results"].includes(entry.name))
      return [];
    const path = resolve(dir, entry.name);
    return entry.isDirectory()
      ? files(path)
      : /\.[cm]?[jt]sx?$/.test(path)
        ? [path]
        : [];
  });
}
const violations = [];
for (const file of [
  ...files(resolve(root, "packages/core/web")),
  ...files(resolve(root, "packages/ui/src")),
  ...files(resolve(root, "packages/features")),
]) {
  const name = relative(root, file);
  const owner = name.match(/^packages\/features\/([^/]+)\/web\//)?.[1];
  if (name.startsWith("packages/features/") && !owner) continue;
  for (const match of readFileSync(file, "utf8").matchAll(
    /(?:from\s*|import\s*)["']([^"']+)["']/g,
  )) {
    const target = match[1];
    const resolved = target.startsWith(".")
      ? relative(root, resolve(dirname(file), target))
      : "";
    const featureTarget = resolved.match(/^packages\/features\/([^/]+)\//)?.[1];
    if (
      target.startsWith("@/") ||
      target.includes("apps/web") ||
      resolved.startsWith("apps/") ||
      (featureTarget && featureTarget !== owner) ||
      (target.startsWith("@clinic/feature-") &&
        !target.startsWith(`@clinic/feature-${owner}/`))
    )
      violations.push(`${name}: forbidden dependency ${target}`);
  }
}
if (violations.length) throw new Error(violations.join("\n"));
console.log(
  "Frontend boundaries passed: shared platform and features have no app or cross-feature imports.",
);
