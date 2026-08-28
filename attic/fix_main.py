with open('C:/Users/21330/Documents/Cortex/frontend/src/app/nexus/page.tsx', 'r') as f:
    lines = f.readlines()

# Fix line 1662: change </main> from 4 spaces to 8 spaces
for i in range(len(lines)):
    if i == 1661 and '</main>' in lines[i]:
        # Get the content after the spaces
        line = lines[i]
        # Replace leading whitespace with 8 spaces
        lines[i] = '        ' + line.lstrip()[6:]  # 8 spaces total + content after 6 stripped
        break

with open('C:/Users/21330/Documents/Cortex/frontend/src/app/nexus/page.tsx', 'w') as f:
    f.writelines(lines)
print('Fixed main indentation to 8 spaces')