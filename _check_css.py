import re

with open("AssetsManager/lan/static/index.html", "r") as f:
    html = f.read()

with open("AssetsManager/lan/static/style.css", "r") as f:
    css = f.read()

html_classes = set()
for m in re.findall(r'class="([^"]+)"', html):
    for cls in m.split():
        html_classes.add(cls)

css_selectors = set()
for m in re.findall(r'\.([a-zA-Z0-9_-]+)\s*\{', css):
    css_selectors.add(m.group(1))

missing = []
for cls in sorted(html_classes):
    if cls not in css_selectors:
        missing.append(cls)

if missing:
    print("=== Classes in HTML not found as direct CSS selectors ===")
    for cls in missing:
        print(f"  .{cls}")
else:
    print("All HTML classes found in CSS.")