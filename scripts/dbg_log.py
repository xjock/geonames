import re
data = open(r'D:/Dev/situation/geonames/vb_full_update.log','rb').read()
text = data.decode('utf-8', errors='replace')
matches = re.findall(r'line (\d+)', text)
print(f'total line refs: {len(matches)}')
print(f'last 20: {matches[-20:]}')
idx = 0
while True:
    p = text.find('KeyError', idx)
    if p < 0: break
    ctx = text[max(0,p-300):p+50]
    print('---')
    print(ctx)
    idx = p + 1
