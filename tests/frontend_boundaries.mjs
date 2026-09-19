// Parse actual TS/Svelte imports; compatibility barrels are not app dependencies.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../frontend/src');
const facades = new Set(['lib/api.ts', 'lib/apiTypes.ts', 'lib/stores.ts']);
function imports(source) {
 const result=[];
 const tree=ts.createSourceFile('fixture.ts',source,ts.ScriptTarget.Latest,true);
 function walk(n){
  if((ts.isImportDeclaration(n)||ts.isExportDeclaration(n))&&n.moduleSpecifier&&ts.isStringLiteral(n.moduleSpecifier))result.push(n.moduleSpecifier.text);
  if(ts.isCallExpression(n)&&n.expression.kind===ts.SyntaxKind.ImportKeyword&&n.arguments[0]&&ts.isStringLiteral(n.arguments[0]))result.push(n.arguments[0].text);
  ts.forEachChild(n,walk);
 }
 walk(tree);return result;
}
assert.deepEqual(imports("import x from './x'; export type {Y} from './y'; import('./z');"),['./x','./y','./z']);
const offenders=[];
function scan(dir){for(const entry of fs.readdirSync(dir,{withFileTypes:true})){
 const file=path.join(dir,entry.name);if(entry.isDirectory()){scan(file);continue;}
 if(!/\.(ts|svelte)$/.test(file))continue;
 const relative=path.relative(root,file).replaceAll('\\','/');
 const raw=fs.readFileSync(file,'utf8');
 const source=file.endsWith('.svelte')?[...raw.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)].map(m=>m[1]).join('\n'):raw;
 for(const spec of imports(source)){
  if(!spec.startsWith('.'))continue;
  let target=path.relative(root,path.resolve(path.dirname(file),spec)).replaceAll('\\','/');
  if(!path.extname(target))target+='.ts';
  const owner=relative.startsWith('modules/')?relative.split('/')[1]:null;
  const destination=target.startsWith('modules/')&&target.split('/').length>=3?target.split('/')[1]:null;
  if(facades.has(target)&&!facades.has(relative))offenders.push(`${relative} -> compatibility ${target}`);
  if(destination&&destination!==owner&&!facades.has(relative)&&!['modules/registry.ts','modules/surfaces.ts','modules/settings.ts'].includes(relative))offenders.push(`${relative} -> ${target}`);
 }
}}
scan(root);
assert.deepEqual(offenders,[],'Module imports must stay behind registration or within their owner');
console.log('PASS: TS and Svelte application imports respect module ownership and avoid compatibility barrels');
