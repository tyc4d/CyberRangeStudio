// Read-only check of this worktree, resolving installed dependencies from the main checkout.
const path = require('node:path');
const ts = require('/home/tyc4d/cr-project/apps/web/node_modules/typescript');
const root = path.resolve(__dirname, '../../../..');
const web = path.join(root, 'apps/web');
const config = ts.readConfigFile(path.join(web, 'tsconfig.json'), ts.sys.readFile);
if (config.error) throw new Error(ts.flattenDiagnosticMessageText(config.error.messageText, '\n'));
const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, web);
const host = ts.createCompilerHost(parsed.options);
const dependencyAnchor = '/home/tyc4d/cr-project/apps/web/src/__m9_review__.tsx';
host.resolveModuleNames = (names, containingFile) => names.map(name => {
  const original = ts.resolveModuleName(name, containingFile, parsed.options, host).resolvedModule;
  if (original || name.startsWith('.') || name === '@contracts') return original;
  return ts.resolveModuleName(name, dependencyAnchor, parsed.options, host).resolvedModule;
});
const program = ts.createProgram(parsed.fileNames, {...parsed.options, noEmit: true}, host);
const diagnostics = [...parsed.errors, ...ts.getPreEmitDiagnostics(program)];
for (const d of diagnostics) {
  const location = d.file && d.start !== undefined ? d.file.getLineAndCharacterOfPosition(d.start) : null;
  console.log(`${d.file ? d.file.fileName : ''}${location ? ':' + (location.line + 1) : ''} TS${d.code}: ${ts.flattenDiagnosticMessageText(d.messageText, '\n')}`);
}
console.log(`Checked ${parsed.fileNames.length} worktree source files; ${diagnostics.length} diagnostics.`);
process.exitCode = diagnostics.length ? 1 : 0;
