"""Quick parse verification script."""
from services.spreadsheet_parser import parse_xlsx

rows, warnings = parse_xlsx(r'e:\jobhunting\local-runner\local-runner\kochi_software_companies.xlsx')
print(f'Parsed: {len(rows)} companies')
print(f'Warnings: {len(warnings)}')
for w in warnings[:8]:
    print(' ', w)

print()
r0 = rows[0]
print('Sample company 1:')
for k, v in r0.items():
    if v:
        print('  ' + k + ': ' + repr(str(v))[:70])

print()
top = sorted(rows, key=lambda r: r.get('match_score') or 0, reverse=True)[:5]
print('Top 5 by match_score:')
for r in top:
    score = str(r.get('match_score') or 0).rjust(3)
    print('  ' + score + ' | ' + r['name'])
