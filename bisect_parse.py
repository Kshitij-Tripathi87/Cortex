"""Bisect page.tsx to find which section breaks Babel parsing."""
import subprocess, sys

BABEL = 'C:/Users/21330/Documents/Cortex/frontend/node_modules/@babel/parser'

def try_parse(code, label):
    test_js = f"""
const parser = require('{BABEL}');
try {{
  parser.parse({repr(code)}, {{ sourceType: 'module', plugins: ['typescript', 'jsx'], errorRecovery: false }});
  console.log('OK');
}} catch (e) {{
  console.log('FAIL line ' + (e.loc?.line || '?') + ': ' + e.message.substring(0, 80));
}}
"""
    with open('C:/Users/21330/Documents/Cortex/_test_parse.js', 'w') as f:
        f.write(test_js)
    r = subprocess.run(['node', 'C:/Users/21330/Documents/Cortex/_test_parse.js'],
                       capture_output=True, text=True, cwd='C:/Users/21330/Documents/Cortex')
    result = r.stdout.strip()
    status = 'OK' if 'OK' in result else 'FAIL'
    print(f'  [{status}] {label}: {result}')
    return status == 'OK'

with open('frontend/src/app/nexus/page.tsx', 'r') as f:
    lines = f.readlines()

total = len(lines)
print(f'Total lines: {total}')
print()

# Test 1: Full file
try_parse(''.join(lines), 'full file')

# Test 2: Truncate after renderSection (line 1031)
# Need a valid component ending: close component function and add return
truncated = ''.join(lines[:1031]) + '\n  return null;\n}'
try_parse(truncated, 'truncated after renderSection (L1031) + return null')

# Test 3: Truncate before renderSection (line 624)
truncated = ''.join(lines[:623]) + '\n  return null;\n}'
try_parse(truncated, 'truncated before renderSection (L624) + return null')

# Test 4: Everything before the component return
truncated = ''.join(lines[:1105]) + '\n  return null;\n}'
try_parse(truncated, 'truncated before component return (L1105) + return null')

# Test 5: Keep only renderSection switch, no return JSX
truncated = ''.join(lines[:1031]) + '\n  return null;\n}'
try_parse(truncated, 'renderSection only (L624-1031) + return null')

# Test 6: First half of file
mid = total // 2
truncated = ''.join(lines[:mid]) + '\n  return null;\n}'
try_parse(truncated, f'first half (L1-{mid}) + return null')
