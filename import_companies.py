"""
import_companies.py — One-shot import of the actual kochi XLSX into the DB.
Run: python import_companies.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from models import Company, db
from services.spreadsheet_parser import parse_xlsx
from pathlib import Path

XLSX_PATH = Path(__file__).parent / "kochi_software_companies.xlsx"

app = create_app()

with app.app_context():
    rows, warnings = parse_xlsx(XLSX_PATH)
    print(f"Parsed {len(rows)} companies, {len(warnings)} warnings.")

    inserted = 0
    skipped  = 0
    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        existing = Company.query.filter(
            db.func.lower(db.func.trim(Company.name)) == name.lower()
        ).first()
        if existing:
            skipped += 1
            continue
        company = Company(**{k: v for k, v in row.items() if v is not None})
        db.session.add(company)
        inserted += 1

    db.session.commit()
    print(f"Done! Inserted: {inserted}  |  Skipped (duplicates): {skipped}")
    print(f"Total companies in DB: {Company.query.count()}")

    # Show top 10 by score
    top = Company.query.order_by(Company.match_score.desc()).limit(10).all()
    print("\nTop 10 companies by match score:")
    for c in top:
        print(f"  {str(c.match_score or 0).rjust(3)}  {c.name}")
