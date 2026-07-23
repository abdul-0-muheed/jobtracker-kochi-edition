"""
services/google_sheets.py — Background sync to Google Apps Script webhook
"""
import threading
import httpx
from flask import current_app

import os
from dotenv import load_dotenv

def _get_webhook_url(app):
    load_dotenv()
    url = os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL")
    if url:
        # Strip quotes if they were accidentally included in the .env file
        return url.strip('"').strip("'")
    return None

def _send_payload_background(app, payload):
    with app.app_context():
        webhook_url = _get_webhook_url(app)
        if not webhook_url:
            return
            
        try:
            # We use a short timeout because it's a background task, we don't want it hanging forever
            # but Apps script can sometimes take a few seconds
            with httpx.Client(timeout=10.0) as client:
                response = client.post(webhook_url, json=payload)
                response.raise_for_status()
        except Exception as e:
            print(f"[Google Sheets Sync Error] {e}")

def trigger_update_company_row(company):
    """
    Sends a single company's data to the Google Sheets webhook to update its row.
    Runs in a background thread to prevent blocking the UI.
    """
    # Extract data before threading to avoid detached session issues
    company_data = {
        "id": company.id,
        "name": company.name,
        "website": company.website,
        "linkedin_url": company.linkedin_url,
        "hr_email": company.hr_email,
        "phone_number": company.phone_number,
        "call_status": company.call_status,
        "contact_status": company.contact_status,
        "notes": company.notes,
        "last_activity_at": company.last_activity_at
    }
    
    payload = {
        "action": "update_row",
        "data": company_data
    }
    
    # We must pass the real app object to the thread
    app = current_app._get_current_object()
    thread = threading.Thread(target=_send_payload_background, args=(app, payload))
    thread.daemon = True
    thread.start()

def trigger_bulk_sync(companies):
    """
    Sends all companies data to the Google Sheets webhook to replace the entire sheet.
    Runs in a background thread.
    """
    companies_data = []
    for company in companies:
        companies_data.append({
            "id": company.id,
            "name": company.name,
            "website": company.website,
            "linkedin_url": company.linkedin_url,
            "hr_email": company.hr_email,
            "phone_number": company.phone_number,
            "call_status": company.call_status,
            "contact_status": company.contact_status,
            "notes": company.notes,
            "last_activity_at": company.last_activity_at
        })
        
    payload = {
        "action": "bulk_sync",
        "data": companies_data
    }
    
    app = current_app._get_current_object()
    thread = threading.Thread(target=_send_payload_background, args=(app, payload))
    thread.daemon = True
    thread.start()
