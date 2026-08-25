const path = require('path');
const parser = require(path.join('C:/Users/21330/Documents/Cortex/frontend/node_modules/@babel/parser'));
const fs = require('fs');
const code = fs.readFileSync('frontend/src/app/nexus/page.tsx', 'utf8');

try {
  parser.parse(code, {
    sourceType: 'module',
    plugins: ['typescript', 'jsx'],
    errorRecovery: false
  });
  console.log('PARSE SUCCESS');
} catch (e) {
  console.log('PARSE ERROR at line', e.loc?.line, 'col', e.loc?.column);
  console.log('Message:', e.message);
  const lines = code.split('\n');
  for (let i = Math.max(0, (e.loc?.line || 1) - 5); i < Math.min(lines.length, (e.loc?.line || 1) + 3); i++) {
    const prefix = (i + 1 === e.loc?.line) ? '>>>' : '   ';
    console.log(prefix + (i+1).toString().padStart(5) + ': ' + lines[i].substring(0, 120));
  }
}
