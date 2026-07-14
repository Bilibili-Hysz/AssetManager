import re

with open("AssetsManager/lan/static/index.html", "r", encoding="utf-8") as f:
    html = f.read()

# Find the app div
idx = html.find('<div class="app" id="app"')
content = html[idx:]

# Get direct children (first-level tags inside app)
# Simple approach: count tag depth
depth = 0
direct_children = []
i = 0
while i < len(content) and depth >= 0:
    if content[i] == '<':
        tag_end = content.find('>', i)
        tag = content[i+1:tag_end]
        if tag.startswith('/'):
            depth -= 1
        elif not tag.startswith('/') and not tag.startswith('!'):
            is_closing = tag.startswith('/')
            if not is_closing and depth == 0:
                # Extract class name
                cls_match = re.search('class="([^"]+)"', tag)
                tag_name = tag.split()[0] if not tag.startswith('/') else tag[1:].split()[0]
                if cls_match:
                    direct_children.append((tag_name, cls_match.group(1)))
                else:
                    direct_children.append((tag_name, ''))
            if not tag.endswith('/') and not tag.startswith('!'):
                depth += 1
        i = tag_end
    else:
        i += 1

print("Direct children of .app:")
for tag, cls in direct_children:
    print(f"  <{tag} class=\"{cls}\">")