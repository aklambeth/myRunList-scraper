#!/bin/bash
set -e

# r2d2h3 endpoint (myfreedevsite.com) is blocked by Codespaces egress filtering
if [ "${CODESPACES}" = "true" ]; then
  python3 -c "
import re
with open('config.yaml') as f: content = f.read()
content = re.sub(r'(  r2d2h3:(?:(?!\n  \w).)*?\n    enabled:) true', r'\1 false', content, flags=re.DOTALL)
with open('config.yaml', 'w') as f: f.write(content)
print('r2d2h3 disabled in config.yaml (myfreedevsite.com unreachable in Codespaces)')
"
fi