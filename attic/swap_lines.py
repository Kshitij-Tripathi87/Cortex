with open('C:/Users/21330/Documents/Cortex/frontend/src/app/nexus/page.tsx', 'r') as f:
    lines = f.readlines()

# Swap lines 1662 and 1663 (0-indexed: 1661 and 1662)
# Current: line 1662 has '</div>', line 1663 has '</main>'
# Need: line 1662 has '</main>', line 1663 has '</div>'

# But also need correct indentation:
# - </main> should be at 8 spaces (matching <main> at line 1153)
# - </div> should be at 4 spaces (matching outer div at line 1106)

# Current lines (from earlier analysis):
# Line 1662: '    </div>\n'    (4 spaces)
# Line 1663: '        </main>\n' (8 spaces)

# We want:
# Line 1662: '        </main>\n'   (8 spaces)
# Line 1663: '    </div>\n'         (4 spaces)

# Swap and adjust indentation
temp = lines[1662]  # '    </div>\n'
lines[1662] = '        </main>\n'   # 8 spaces for </main>
lines[1663] = temp                   # 4 spaces for </div> (was '    </div>\n')

with open('C:/Users/21330/Documents/Cortex/frontend/src/app/nexus/page.tsx', 'w') as f:
    f.writelines(lines)
print('Lines swapped and indentation fixed')