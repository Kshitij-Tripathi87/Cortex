with open('src/app/nexus/page.tsx', 'r') as f:
    lines = f.readlines()

code = ''.join(lines[:1105])
open_brace = code.count('{')
close_brace = code.count('}')
open_par = code.count('(')
close_par = code.count(')')

print(f'From line 1 to 1105:')
print(f'  Braces: open={open_brace}, close={close_brace}, diff={open_brace - close_brace}')
print(f'  Parens: open={open_par}, close={close_par}, diff={open_par - close_par}')

full = ''.join(lines)
print(f'\nWhole file:')
print(f'  Braces: open={full.count("{")}, close={full.count("}")}, diff={full.count("{") - full.count("}")}')
print(f'  Parens: open={full.count("(")}, close={full.count(")")}, diff={full.count("(") - full.count(")")}')

# Also check specific section: renderSection start to line 1105
rs_start = None
for i, line in enumerate(lines):
    if 'const renderSection' in line:
        rs_start = i
        break

if rs_start:
    code_rs = ''.join(lines[rs_start:1105])
    open_brace_rs = code_rs.count('{')
    close_brace_rs = code_rs.count('}')
    open_par_rs = code_rs.count('(')
    close_par_rs = code_rs.count(')')
    print(f'\nrenderSection from line {rs_start+1} to 1105:')
    print(f'  Braces: open={open_brace_rs}, close={close_brace_rs}, diff={open_brace_rs - close_brace_rs}')
    print(f'  Parens: open={open_par_rs}, close={close_par_rs}, diff={open_par_rs - close_par_rs}')