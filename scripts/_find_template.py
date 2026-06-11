text = open('web/app.py', encoding='utf-8').read()
idx = text.find('HTML_TEMPLATE')
print(f'HTML_TEMPLATE starts at line {text[:idx].count(chr(10))+1}')
# find the closing triple quote
start = text.find("'''", idx)
end = text.find("'''", start + 3)
print(f"Template: char {start} to {end}")
print(f"After template line: {text[:end+3].count(chr(10))+1}")
