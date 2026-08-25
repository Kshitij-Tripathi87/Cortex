with open('frontend/src/app/nexus/page.tsx', 'r') as f:
    lines = f.readlines()

# Find the World section's opening
for i in range(len(lines)):
    if 'section === "World"' in lines[i]:
        print(f'L{i+1}: {lines[i].rstrip()[:80]}')

# Also list all lines with "World" or "world" in conditional contexts
for i in range(1245, 1260):
    print(f'L{i+1}: {lines[i].rstrip()[:100]}')
