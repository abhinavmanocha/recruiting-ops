"""Find JS syntax error in template/index.html"""
import re
import subprocess

with open('D:/Projects/recruiting-ops/templates/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

m = re.search(r'<script>(.*?)</script>', content, re.DOTALL)
if not m:
    print("No script")
    exit()

js = m.group(1)

# Test the whole thing
with open('D:/Projects/recruiting-ops/test_whole.js', 'w') as f:
    f.write(js)

result = subprocess.run(
    ['node', '--check', 'D:/Projects/recruiting-ops/test_whole.js'], 
    capture_output=True, text=True, timeout=10
)

if result.returncode != 0:
    print(f"ERROR: {result.stderr.strip()}")
    # Parse line number
    m2 = re.search(r'[^(]*\((\d+):(\d+)\)', result.stderr)
    if m2:
        line_no = int(m2.group(1))
        col_no = int(m2.group(2))
        lines = js.split('\n')
        start = max(0, line_no - 5)
        end = min(len(lines), line_no + 2)
        for i in range(start, end):
            marker = '>>>' if i == line_no - 1 else '   '
            print(f'{marker} {i+1}: {lines[i][:150]}')
else:
    print("All JS OK!")

import os
os.remove('D:/Projects/recruiting-ops/test_whole.js')
