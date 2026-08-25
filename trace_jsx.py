import re
with open('frontend/src/app/nexus/page.tsx', 'r') as f:
    lines = f.readlines()

# Simple JSX element stack tracker — focused on <div, </div>, <main, </main>, etc.
# Plus conditional expressions: {cond && (...)} and {cond ? ( ... ) : (...)}
tag_stack = []
paren_stack = []
brace_stack = []

in_string = None  # '", "', '`', or None
in_jsx_comment = False  # {/* ... */}

for i in range(620, len(lines)):
    raw = lines[i]
    line = raw.rstrip('\n')
    j = 0
    while j < len(line):
        ch = line[j]

        # Handle strings
        if in_string:
            if ch == in_string and (j == 0 or line[j-1] != '\\'):
                in_string = None
            j += 1
            continue

        # Handle JSX comments {/* ... */}
        if in_jsx_comment:
            if line[j:j+2] == '*/':
                in_jsx_comment = False
                j += 2
            else:
                j += 1
            continue

        if line[j:j+3] == '{/*':
            in_jsx_comment = True
            brace_stack.append(('comment', i + 1, line.strip()[:40]))
            j += 3
            continue

        # JSX expression { ... } (but not JSX comments)
        if ch == '{' and j + 1 < len(line) and line[j+1] != '*':
            brace_stack.append(('brace', i + 1, line.strip()[:40]))
        # Close brace } (but not inside JSX comment)
        elif ch == '}' and not in_jsx_comment:
            if brace_stack:
                brace_stack.pop()

        # Track opening tags and closing tags
        # Look for <tagName or </tagName
        if ch == '<':
            close_match = re.match(r'^</(\w+)', line[j:])
            open_match = re.match(r'^<(\w+)', line[j:])

            if close_match:
                tag_name = close_match.group(1)
                if tag_stack and tag_stack[-1][0] == tag_name:
                    tag_stack.pop()
            elif open_match:
                tag_name = open_match.group(1)
                # Self-closing?
                rest = line[j + open_match.end():]
                if '/>' in rest:
                    # Find if '/> before '>'
                    idx = rest.find('/>')
                    gt_idx = rest.find('>')
                    if idx != -1 and (gt_idx == -1 or idx < gt_idx):
                        tag_stack.append((tag_name, i + 1, line.strip()[:50]))
                    else:
                        tag_stack.append((tag_name, i + 1, line.strip()[:50]))
                elif '>' in rest:
                    tag_stack.append((tag_name, i + 1, line.strip()[:50]))
                else:
                    tag_stack.append((tag_name, i + 1, line.strip()[:50]))

        # Track parens for conditional expressions
        if ch == '(' and not in_string:
            paren_stack.append(('paren', i + 1, line.strip()[:40]))
        elif ch == ')' and not in_string:
            # Check if this closes a conditional expression
            if paren_stack and paren_stack[-1][0] == 'paren':
                paren_stack.pop()
            else:
                # This might be part of closing a JSX conditional )} 
                pass

        j += 1

print('Uncollected JSX tags (from line 620+):')
for tag in tag_stack:
    print(f'  {tag[0]} at L{tag[1]}: {tag[2]}')
print()
print('Unclosed braces:')
for b in brace_stack:
    print(f'  L{b[1]}: {b[2]}')
print()
print('Unclosed parens:')
for p in paren_stack:
    print(f'  L{p[1]}: {p[2]}')
