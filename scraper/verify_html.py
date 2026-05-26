import re
content = open("raw/rvf_pages/rvf_price_research.html", encoding="utf-8").read()
cells = re.findall(r'<td class="price[^"]*"[^>]*>.*?</td>', content[:12000], re.DOTALL)
for c in cells[:8]:
    print(c[:220])
    print()
