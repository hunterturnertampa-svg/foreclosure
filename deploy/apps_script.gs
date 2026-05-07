// deploy/apps_script.gs
// PASTE THIS into a new Apps Script attached to your Google Sheet.
// 1. Replace SHARED_TOKEN with the same value you set for SHEETS_WEBHOOK_TOKEN in .env.
// 2. Add a tab named "Leads" with headers in row 1:
//    Written At | Case # | Date Filed | Owner Name | Street | City | State | Zip | Mobile 1 | Mobile 2 | Mobile 3
// 3. Deploy → New deployment → Type: Web app → Execute as: Me, Access: Anyone with the link.
// 4. Copy the Web App URL into SHEETS_WEBHOOK_URL in .env.

const SHARED_TOKEN = 'replace-me-with-SHEETS_WEBHOOK_TOKEN';

function doPost(e) {
  let body = {};
  try { body = JSON.parse(e.postData.contents); } catch (err) {
    return _resp({ ok: false, error: 'bad_json' });
  }
  if (body.token !== SHARED_TOKEN) {
    return _resp({ ok: false, error: 'unauthorized' });
  }
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Leads');
  if (!sheet) return _resp({ ok: false, error: 'no_leads_tab' });
  sheet.appendRow([
    new Date(),
    body.case_number, body.date_filed,
    body.owner_name,
    body.street, body.city, body.state, body.zip,
    body.mobile_1 || '', body.mobile_2 || '', body.mobile_3 || ''
  ]);
  return _resp({ ok: true });
}

function _resp(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
