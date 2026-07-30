"""Find JS syntax error in template/index.html by testing code blobs"""
import re
import subprocess
import os

with open('D:/Projects/recruiting-ops/templates/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

m = re.search(r'<script>(.*?)</script>', content, re.DOTALL)
if not m:
    print("No script")
    exit()

js = m.group(1)

# Split JS into functions
# Find all top-level functions and their start positions
func_starts = []
for match in re.finditer(r'^(async\s+)?function\s+\w+\s*\(|^\w+\s*=\s*\(|^document\.|^let\s+\w+|^const\s+\w+', js, re.MULTILINE):
    func_starts.append(match.start())

# Try to compile each segment using node
for i, start in enumerate(func_starts):
    end = func_starts[i+1] if i+1 < len(func_starts) else len(js)
    segment = js[:end]
    
    # Write to temp file and test with node
    with open('/tmp/test_js.js', 'w') as f:
        f.write(segment)
    
    result = subprocess.run(
        ['node', '--check', '/tmp/test_js.js'], 
        capture_output=True, text=True, timeout=5
    )
    
    if result.returncode != 0:
        # Show what was added since last successful segment
        prev_end = func_starts[i-1] if i > 0 else 0
        added = js[prev_end:end]
        print(f"ERROR at function {i}: {result.stderr.strip()}")
        print(f"--- Added code (first 500 chars) ---")
        print(added[:500])
        print(f"--- Last 300 chars ---")
        print(added[-300:])
        break
else:
    print("All JS OK!")
