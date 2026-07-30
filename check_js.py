"""Check JS syntax errors in index.html"""
import re

with open('D:/Projects/recruiting-ops/templates/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

m = re.search(r'<script>(.*?)</script>', content, re.DOTALL)
if not m:
    print("No script tag found")
    exit()

js = m.group(1)
lines = js.split('\n')
depth = 0
in_template = False
for i, line in enumerate(lines, 1):
    prev_depth = depth
    for ch in line:
        if ch == '`':
            in_template = not in_template
        if not in_template:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
    if depth != prev_depth:
        print(f'Line {i}: depth {prev_depth} -> {depth}: {line.strip()[:100]}')

print(f'Final depth: {depth}')
if depth != 0:
    if depth < 0:
        print(f'UNBALANCED! Missing {-depth} opening braces')
    else:
        print(f'UNBALANCED! Missing {depth} closing braces')
