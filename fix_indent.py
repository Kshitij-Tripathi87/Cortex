with open('C:/Users/21330/Documents/Cortex/frontend/src/app/nexus/page.tsx', 'r') as f:
    lines = f.readlines()

# Fix line 1662: change </main> from 4 spaces to 8 spaces
for i in range(len(lines)):
    if i == 1661 and '</main>' in lines[i]:
        # Replace with 8 spaces
        line = lines[i]
        lines[i] = '        ' + line.lstrip()[6:]  # 8 spaces total + content
        break

with open('C:/Users/21330/Documents/Cortex/frontend/src/app/nexus/page.tsx', 'w') as f:
    f.writelines(lines)
print('Fixed main indentation to 8 spaces')