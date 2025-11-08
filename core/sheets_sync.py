from google.oauth2 import service_account
from googleapiclient.discovery import build
from django.conf import settings
from .models import Booking, SystemConfig
import hashlib
import json
import logging
from datetime import datetime
from django.utils import timezone

logger = logging.getLogger(__name__)

class GoogleSheetsSyncService:
    def __init__(self):
        """Initialize Google Sheets API connection - works with file path OR JSON string"""
        try:
            google_key = settings.GOOGLE_KEY_FILE
            
            # Determine if it's a file path or JSON string
            # File paths won't start with '{' and will be relatively short
            if google_key.strip().startswith('{'):
                # It's a JSON string - parse and load directly
                try:
                    credentials_dict = json.loads(google_key)
                    credentials = service_account.Credentials.from_service_account_info(
                        credentials_dict,
                        scopes=['https://www.googleapis.com/auth/spreadsheets']
                    )
                    logger.info("Loaded Google credentials from JSON string (production)")
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSON in GOOGLE_KEY_FILE: {str(e)}")
            elif os.path.isfile(google_key):
                # It's a file path - load from file
                credentials = service_account.Credentials.from_service_account_file(
                    google_key,
                    scopes=['https://www.googleapis.com/auth/spreadsheets']
                )
                logger.info(f"Loaded Google credentials from file: {google_key}")
            else:
                raise ValueError(
                    f"GOOGLE_KEY_FILE must be either a valid file path or JSON string. "
                    f"Got something that's neither a file nor valid JSON: {google_key[:50]}..."
                )

            self.sheets_service = build('sheets', 'v4', credentials=credentials)
            self.spreadsheet_id = settings.SPREADSHEET_ID
            self.sheet_name = getattr(settings, 'SHEET_NAME', 'Sheet1')

            logger.info(f"Google Sheets service initialized - Sheet: {self.sheet_name}")
        except Exception as e:
            logger.error(f"Failed to initialize Google Sheets service: {str(e)}")
            raise

    def get_sheet_range(self, range_str):
        """Return properly quoted sheet range for Google Sheets API"""
        escaped_name = self.sheet_name.replace("'", "''")
        return f"'{escaped_name}'!{range_str}"
    
    def generate_sync_hash(self, data):
        """Generate MD5 hash to prevent sync loops"""
        return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()
    
    def get_payable_status(self, booking):
        """Convert booking approval status to sheet status"""
        if booking.status == 'confirmed':
            return 'Payable'
        elif booking.status == 'declined':
            return 'Non Payable'
        else:
            return 'Pending'
    
    def get_approval_status_from_sheet(self, sheet_status):
        """Convert sheet status to booking approval status"""
        if sheet_status == 'Payable':
            return 'confirmed'
        elif sheet_status == 'Non Payable':
            return 'declined'
        else:
            return 'pending'
    
    def sync_new_booking_to_sheet(self, booking):
        """
        Sync a newly created 'live_transfer' booking to Google Sheets.
        Only syncs if appointment_type is live_transfer.
        """
        if booking.appointment_type != 'live_transfer':
            logger.info(f"Booking {booking.id} is not a live transfer, skipping sheet sync")
            return False
        
        if booking.sheet_row_number:
            logger.info(f"Booking {booking.id} already synced to row {booking.sheet_row_number}")
            return False
        
        try:
            # Prepare row data
            row_data = [
                booking.id,
                booking.created_at.strftime('%m/%d'),
                booking.client.first_name,
                booking.client.last_name or '',
                booking.client.phone_number,
                booking.resort or '',
                str(booking.mortgage_balance) if booking.mortgage_balance else '',
                str(booking.maintenance_fees) if booking.maintenance_fees else '',
                booking.created_by.get_full_name() if booking.created_by else '',
                booking.client.specialist_name or '',
                self.get_payable_status(booking),
                booking.notes or ''
            ]
            
            sync_hash = self.generate_sync_hash({'approval_status': booking.status})
            
            body = {'values': [row_data]}
            result = self.sheets_service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range=self.get_sheet_range('A:L'),  # Changed to L for 12 columns (including notes)
                valueInputOption='USER_ENTERED',
                body=body
            ).execute()
            
            # Get the row number
            updated_range = result.get('updates', {}).get('updatedRange', '')
            if ':' in updated_range:
                row_part = updated_range.split('!')[1].split(':')[0]
                row_number = int(''.join(filter(str.isdigit, row_part)))
            else:
                sheet_data = self.sheets_service.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id,
                    range=self.get_sheet_range('A:A')
                ).execute()
                row_number = len(sheet_data.get('values', [])) + 1
            
            # FIXED: Use timezone.now() instead of datetime.now()
            booking.sheet_row_number = row_number
            booking.sheet_sync_hash = sync_hash
            booking.last_synced_at = timezone.now()
            booking.save(update_fields=['sheet_row_number', 'sheet_sync_hash', 'last_synced_at'])
            
            logger.info(f"Booking {booking.id} synced to sheet row {row_number}")
            return True
            
        except Exception as e:
            logger.error(f"Error syncing booking {booking.id} to sheet: {str(e)}")
            return False
    
    def update_sheet_from_booking(self, booking):
        """Update sheet when booking approval status changes in DB"""
        if not booking.sheet_row_number:
            logger.warning(f"Booking {booking.id} not yet in sheet")
            return False
        
        try:
            payable_status = self.get_payable_status(booking)
            new_hash = self.generate_sync_hash({'approval_status': booking.status})
            
            if booking.sheet_sync_hash == new_hash:
                logger.info(f"Sync hash matches for booking {booking.id}, skipping to prevent loop")
                return False
            
            # Update the Payable/Non-Payable cell (column K)
            body = {'values': [[payable_status]]}
            self.sheets_service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=self.get_sheet_range(f'K{booking.sheet_row_number}'),
                valueInputOption='USER_ENTERED',
                body=body
            ).execute()
            
            # FIXED: Use timezone.now()
            booking.sheet_sync_hash = new_hash
            booking.last_synced_at = timezone.now()
            booking.save(update_fields=['sheet_sync_hash', 'last_synced_at'])
            
            logger.info(f"Updated sheet row {booking.sheet_row_number} for booking {booking.id}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating sheet for booking {booking.id}: {str(e)}")
            return False
    
    def sync_sheet_changes_to_db(self):
        """Check sheet for changes and update DB accordingly"""
        try:
            result = self.sheets_service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=self.get_sheet_range('A2:L')  # Changed to include all columns
            ).execute()
            
            rows = result.get('values', [])
            updated_count = 0
            
            for i, row in enumerate(rows):
                row_number = i + 2
                
                if len(row) < 11:
                    continue
                
                booking_id = row[0]
                sheet_payable_status = row[10] if len(row) > 10 else 'Pending'
                
                if not booking_id:
                    continue
                
                try:
                    booking = Booking.objects.get(id=booking_id)
                except Booking.DoesNotExist:
                    logger.warning(f"Booking {booking_id} not found in DB")
                    continue
                
                db_status = self.get_approval_status_from_sheet(sheet_payable_status)
                new_hash = self.generate_sync_hash({'approval_status': db_status})
                
                if booking.status != db_status and booking.sheet_sync_hash != new_hash:
                    booking.status = db_status
                    booking.sheet_sync_hash = new_hash
                    booking.last_synced_at = timezone.now()  # FIXED: Use timezone.now()
                    
                    # FIXED: Use timezone.now() for approval/decline timestamps
                    if db_status == 'confirmed' and not booking.approved_at:
                        booking.approved_at = timezone.now()
                    elif db_status == 'declined' and not booking.declined_at:
                        booking.declined_at = timezone.now()
                    
                    booking.save()
                    updated_count += 1
                    logger.info(f"Updated booking {booking_id} from sheet: {db_status}")
            
            logger.info(f"Sheet sync completed: {updated_count} bookings updated")
            return updated_count
            
        except Exception as e:
            logger.error(f"Error syncing from sheet: {str(e)}")
            return 0
    
    def initialize_sheet(self):
        """Initialize sheet with headers if empty"""
        try:
            result = self.sheets_service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=self.get_sheet_range('A1:L1')  # Changed to L for notes column
            ).execute()

            if not result.get('values'):
                headers = [[
                    'ID', 'Date', 'First Name', 'Last Name', 'Phone Number', 
                    'Resort', 'PIF/Mortgage', 'Fees', 'Transfer Agent', 
                    'CETS Rep', 'Payable/Non Payable', 'Notes'
                ]]
                body = {'values': headers}
                self.sheets_service.spreadsheets().values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range=self.get_sheet_range('A1:L1'),
                    valueInputOption='USER_ENTERED',
                    body=body
                ).execute()
                logger.info("Sheet headers initialized")

            return True
        except Exception as e:
            logger.error(f"Error initializing sheet: {str(e)}")
            return False