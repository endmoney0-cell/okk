import re,sys,html
s=open(sys.argv[1],encoding='utf-8',errors='ignore').read()
t=re.search(r'<title>(.*?)</title>',s); print('TITLE',t.group(1) if t else None)
for m in re.finditer(r'<a href="([^"]+)"[^>]*>.*?flip-entry-title">(.*?)</div>.*?flip-entry-last-modified"><div>(.*?)</div>',s,re.S):
    print('  ',html.unescape(m.group(2)),'|',m.group(1).split('/d/')[-1].split('/folders/')[-1].split('/')[0].split('?')[0],'|',m.group(3))
