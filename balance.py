with open('C:/Users/21330/Documents/Cortex/frontend/src/app/nexus/page.tsx', 'r') as f:
    lines = f.readlines()

# Check balance up to line 1483
code = ''.join(lines[:1483])
open_brace = code.count('{')
close_brace = code.count('}')
open_par = code.count('(')
close_par = code.count(')')
print(f'Up to line 1483:')
print(f'  Braces: open={open_brace}, close={close_brace}, diff={open_brace - close_brace}')
print(f'  Parens: open={open_par}, close={close_par}, diff={open_par - close_par}')

# Check balance from line 1484 to end
code2 = ''.join(lines[1484:])
open_brace2 = code2.count('{')
close_brace2 = code2.count('}')
open_par2 = code2.count('(')
close_par2 = code2.count(')')
print(f'\nFrom line 1484 to end:')
print(f'  Braces: open={open_brace2}, close={close_brace2}, diff={open_brace2 - close_brace2}')
print(f'  Parens: open={open_par2}, close={close_par2}, diff={open_par2 - close_par2}')

# Whole file
full = ''.join(lines)
print(f'\nWhole file:')
import sys
print(f'  Braces: open={full.count("{{")}, close={full.count("}}")}, diff={full.count("{{") - full.count("}}")}')
# Actually count single braces
db = full.count('{')
dc = full.count('}')
print(f'  Braces: open={db}, close={dc}, diff={db - dc}')
par = full.count('(')
pc = full.count(')')
print(f'  Parens: open={par}, close={pc}, diff={par - pc}')