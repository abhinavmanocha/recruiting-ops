"""Validate the JS inside templates/index.html"""
import re
import subprocess

with open('D:/Projects/recruiting-ops/templates/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

m = re.search(r'<script>(.*?)</script>', content, re.DOTALL)
if not m:
    print("No script")
    exit()

js = m.group(1)
with open('D:/Projects/recruiting-ops/test_whole.js', 'w') as f:
    f.write(js)

result = subprocess.run(
    ['node', '--check', 'D:/Projects/recruiting-ops/test_whole.js'],
    capture_output=True, text=True, timeout=10
)

if result.returncode != 0:
    print(f"ERROR: {result.stderr.strip()}")
else:
    print("All JS OK!")

import os
os.remove('D:/Projects/recruiting-ops/test_whole.js')
