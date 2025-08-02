import os
import json
import datetime
import uuid
from flask import Flask, request, jsonify, Response
from textmagic.rest import TextmagicRestClient
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key')

# Initialize TextMagic client
try:
    textmagic_client = TextmagicRestClient(
        username=os.getenv('TEXTMAGIC_USERNAME'),
        token=os.getenv('TEXTMAGIC_API_KEY')
    )
    TEXTMAGIC_PHONE_NUMBER = os.getenv('TEXTMAGIC_PHONE_NUMBER')
except Exception as e:
    print(f"Error initializing TextMagic client: {e}")
    textmagic_client = None

# Google Sheets setup
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
SHEET_ID = os.getenv('SPREADSHEET_ID')
SERVICE_ACCOUNT_FILE = os.getenv('SERVICE_ACCOUNT_FILE', 'service-account.json')

# Write the service account JSON to a file
try:
    os.makedirs(os.path.dirname(SERVICE_ACCOUNT_FILE) or '.', exist_ok=True)
    with open(SERVICE_ACCOUNT_FILE, 'w') as f:
        f.write(os.getenv('GOOGLE_SHEETS_CREDENTIALS', '{}'))
except Exception as e:
    print(f"Error writing service account file: {e}")

# In-memory storage for active job requests (in production, use a database)
active_requests = {}

def get_providers(location):
    """Fetch providers from Google Sheets based on location"""
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build('sheets', 'v4', credentials=creds)
        
        # Assuming the sheet name is 'Providers' and has columns: Name, Phone, Location, Status
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range='Providers!A2:D'
        ).execute()
        
        values = result.get('values', [])
        if not values:
            return []
            
        # Filter providers by location and return as list of dicts
        providers = []
        for row in values:
            if len(row) >= 4 and row[2].lower() == location.lower():
                providers.append({
                    'name': row[0],
                    'phone': row[1],
                    'location': row[2],
                    'status': row[3] if len(row) > 3 else 'active'
                })
        return providers
    except HttpError as error:
        print(f"An error occurred: {error}")
        return []

def send_sms(to_number, message):
    """Send SMS using TextMagic"""
    if not textmagic_client:
        print("TextMagic client not initialized")
        return None
        
    try:
        # Remove any non-digit characters from the phone number
        to_number = ''.join(filter(str.isdigit, to_number))
        
        # Send the message
        result = textmagic_client.messages.create(
            phones=to_number,
            text=message,
            from_number=TEXTMAGIC_PHONE_NUMBER
        )
        return result.id
    except Exception as e:
        print(f"Error sending SMS: {e}")
        return None

def extract_form_data(data):
    """Extract and format form data from Fluent Forms webhook"""
    # Initialize with default values
    result = {
        'client_name': '',
        'client_phone': '',
        'massage_type': 'massage',
        'date': '',
        'time': '',
        'duration': '',
        'city': '',
        'special_requests': ''
    }
    
    # Get the form response data
    response = data.get('response', {})
    
    # Map Fluent Forms fields to our data structure
    # Update these mappings based on your actual form field names/IDs
    field_mapping = {
        'client_name': ['inputs.names.first_name', 'name', 'full_name'],
        'client_phone': ['labels.phone', 'phone', 'phone_number'],
        'massage_type': ['inputs.dropdown', 'massage_type', 'service_type'],
        'date': ['inputs.datetime', 'date', 'appointment_date'],
        'time': ['time', 'appointment_time', 'time_slot'],
        'duration': ['duration', 'session_length', 'time_duration'],
        'city': ['city', 'location', 'address.city'],
        'special_requests': ['special_requests', 'notes', 'message']
    }
    
    # Helper function to find a value in the response
    def find_value(keys):
        if not isinstance(keys, list):
            keys = [keys]
        for key in keys:
            if key in response:
                return response[key]
        return ''
    
    # Extract each field
    for field, possible_keys in field_mapping.items():
        result[field] = find_value(possible_keys)
    
    return result

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    """Handle incoming webhook from Fluent Forms"""
    try:
        data = request.json
        print("Received webhook data:", json.dumps(data, indent=2))  # Debug log
        
        # Extract job ID and basic info
        job_id = data.get('entry_id', str(uuid.uuid4()))  # Generate a UUID if not provided
        
        # Extract all form data using our mapping function
        booking_details = extract_form_data(data)
        
        # Use the city from the form data as the location
        location = booking_details.get('city', '')
    
        # Create a human-readable job details string for logging
        job_details = (
            f"New {booking_details.get('duration', '')} {booking_details.get('massage_type', 'massage')} "
            f"booking in {location} on {booking_details.get('date', '')} at {booking_details.get('time', '')}"
        )
        
        if not location:
            return jsonify({'error': 'Location (city) is required'}), 400
        
        # Get providers for this location
        providers = get_providers(location)
        if not providers:
            return jsonify({'error': 'No providers found for this location'}), 404
        
        # Store the job request with the list of providers and booking details
        active_requests[job_id] = {
            'providers': providers,
            'current_provider_index': 0,
            'job_details': job_details,
            'booking_details': booking_details,
            'status': 'pending',
            'location': location,
            'created_at': datetime.datetime.now().isoformat()
        }
    
        # Notify the first provider
        notify_next_provider(job_id)
        
        return jsonify({
            'status': 'success', 
            'message': 'Job request received',
            'job_id': job_id
        })
        
    except Exception as e:
        print(f"Error processing webhook: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Error processing request: {str(e)}'
        }), 500

def notify_next_provider(job_id):
    """Notify the next available provider about the job"""
    if job_id not in active_requests:
        return False
    
    job = active_requests[job_id]
    providers = job['providers']
    current_index = job['current_provider_index']
    
    if current_index >= len(providers):
        # No more providers to notify
        job['status'] = 'no_providers_available'
        return False
    
    provider = providers[current_index]
    
    # Extract booking details from the job
    booking = job.get('booking_details', {})
    
    # Format the message with booking details
    message = (
        f"Hey {provider['name']}, you've been booked for a "
        f"{booking.get('massage_type', 'massage')} in "
        f"{booking.get('city', 'the city')} at "
        f"{booking.get('date', 'the scheduled time')}. "
        f"Client: {booking.get('client_name', 'New Client')} "
        f"(Phone: {booking.get('client_phone', 'N/A')}).\n\n"
        "Please reply with 'ACCEPT' to confirm this booking or 'DECLINE' if you're not available.\n"
        "Thanks!"
    )
    
    # Send the SMS
    send_sms(provider['phone'], message)
    
    # Update the job status
    job['current_provider'] = provider
    job['status'] = 'waiting_for_response'
    
    return True

@app.route('/incoming-sms', methods=['POST'])
def handle_sms():
    """Handle incoming SMS responses from providers via TextMagic webhook"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'No data received'}), 400
            
        # Extract message details from TextMagic webhook
        message_data = data.get('message', {})
        from_number = message_data.get('from')
        body = (message_data.get('text', '') or '').strip().upper()
        
        if not from_number or not body:
            return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400
        
        # Find the job this provider is responding to
        job_id = None
        for jid, job in active_requests.items():
            if job.get('status') == 'waiting_for_response' and \
               job.get('current_provider', {}).get('phone') == from_number:
                job_id = jid
                break
        
        if not job_id:
            # No active job found for this number
            send_sms(from_number, "No active job request found for your number.")
            return jsonify({'status': 'success'})
        
        job = active_requests[job_id]
        
        if body == 'ACCEPT':
            # Provider accepted the job
            provider = job['current_provider']
            job['status'] = 'accepted'
            job['accepted_by'] = provider
            
            # Send confirmation to provider
            send_sms(from_number, f"Thank you for accepting the job, {provider['name']}! You will be contacted with further details.")
            
            # TODO: Notify the system about the acceptance
            
        elif body == 'DECLINE':
            # Provider declined, move to next provider
            provider = job['current_provider']
            job['current_provider_index'] += 1
            
            # Notify next provider if available
            if not notify_next_provider(job_id):
                send_sms(from_number, "Thank you for your response. No more providers available for this job.")
            else:
                send_sms(from_number, "Thank you for your response. We'll notify the next available provider.")
        else:
            # Invalid response
            send_sms(from_number, "Please reply with 'ACCEPT' to take this job or 'DECLINE' to pass.")
        
        return jsonify({'status': 'success'})
        
    except Exception as e:
        print(f"Error handling incoming SMS: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_ENV') == 'development')
