import re

with open("AssetsManager/lan/static/index.html", "r", encoding="utf-8") as f:
    html = f.read()

with open("AssetsManager/lan/static/style.css", "r", encoding="utf-8", errors="replace") as f:
    css = f.read()

html_classes = set()
for m in re.findall('class="([^"]+)"', html):
    for cls in m.split():
        html_classes.add(cls)

css_selectors = set()
for m in re.findall(r'\.([a-zA-Z0-9_-]+)\s*\{', css):
    css_selectors.add(m.group(1))

# Also check for compound selectors like .parent .child
# by looking for patterns that match HTML classes

missing = []
for cls in sorted(html_classes):
    if cls not in css_selectors:
        # Check if it might be defined as .something.somethingelse
        parts = cls.split("--")
        base = parts[0]
        if base not in css_selectors:
            missing.append(cls)

if missing:
    print("=== Classes in HTML possibly missing from CSS ===")
    for cls in missing:
        print(f"  .{cls}")
else:
    print("All HTML classes have corresponding CSS selectors.")
    print(f"  HTML classes: {len(html_classes)}, CSS selectors: {len(css_selectors)}")