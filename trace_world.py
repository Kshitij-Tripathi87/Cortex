with open('frontend/src/app/nexus/page.tsx', 'r') as f:
    lines = f.readlines()

# Trace through the World section and the right rail area
# World section starts at L1248 with {section === "World" && (
# and should end when the corresponding )} is found
# The <main> at L1153 contains all this

div_depth = 0
main_depth = 0
in_world = False
world_start = None

print("=== JSX element tracking for lines 1248-1490 ===")
print("Format: L<line>: [<stack>] content")
print()

for i in range(1247, 1490):  # 0-indexed: line 1248 is index 1247
    line = lines[i].rstrip()
    stripped = line.strip()
    spaces = len(line) - len(line.lstrip())

    status = ''

    # Track section conditionals
    if '{section === "World" && (' in line:
        div_depth += 1
        status = f'OPEN World conditional | div_depth={div_depth}'
    elif '{section !== "Overview" && section !== "World" && (' in line:
        div_depth += 1
        status = f'OPEN section conditional | div_depth={div_depth}'

    # Track self-closing tags
    elif '/>' in line and not stripped.startswith('</'):
        # Self-closing tag - doesn't affect depth
        status = 'SELF-CLOSING'

    # Track opening tags
    elif '<div' in line and not stripped.startswith('</'):
        div_depth += 1
        tag_desc = line.strip()[:60]
        status = f'OPEN div (depth={div_depth})'

    # Track closing tags
    elif '</div>' in stripped and '<div' not in stripped:
        div_depth -= 1
        status = f'CLOSE div (depth={div_depth})'
        if div_depth < 0:
            status += ' <<< PROBLEM'

    # Track JSX expression closes )}
    elif stripped == ')}':
        div_depth -= 1
        status = f'CLOSE conditional (depth={div_depth})'
        if div_depth < 0:
            status += ' <<< PROBLEM'

    # Track aside
    elif '<aside' in stripped:
        status = 'OPEN <aside>'
    elif '</aside>' in stripped:
        status = 'CLOSE </aside>'

    if status and (stripped and not stripped.startswith('//') and not stripped.startswith('/*')):
        print(f'L{i+1}: [{spaces:2d}s] {stripped[:70]} | {status}')

print()
print(f'Final div_depth: {div_depth}')
print(f'Expected final div_depth: 0')
