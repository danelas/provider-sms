# Provider Notification System

A webhook handler for Fluent Forms that manages job acceptance via SMS using Twilio and Google Sheets integration.

## Setup Instructions

### Prerequisites

1. Python 3.9+
2. A TextMagic account with an active phone number and API access
3. A Google Cloud Project with Google Sheets API enabled
4. Service account credentials for Google Sheets API
5. A Google Spreadsheet with provider information

### Installation

1. Clone this repository
2. Install the required packages:
   ```
   pip install -r requirements.txt
   ```
3. Create a `.env` file based on `.env.example` and fill in your credentials
4. Deploy to Render using the button below:

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/yourusername/provider-notification-system)

### Environment Variables

1. Create a `.env` file in the root directory with the following variables:
   ```
   GOOGLE_SHEETS_API=your_service_account_json_here
   SPREADSHEET_ID=your_google_sheet_id
   TEXTMAGIC_USERNAME=your_textmagic_username
   TEXTMAGIC_API_KEY=your_textmagic_api_key
   TEXTMAGIC_PHONE_NUMBER=your_textmagic_phone_number
   SECRET_KEY=your_secret_key_here
   ```
2. For production, set these as environment variables in your hosting platform.
3. The `GOOGLE_SHEETS_API` should be the full JSON content of your Google service account key file.

### Google Sheets Format

Your Google Sheet should have a tab named "Providers" with the following columns:
- Column A: Provider Name
- Column B: Phone Number (in E.164 format, e.g., +1234567890)
- Column C: Location
- Column D: Status (optional)

### Fluent Forms Setup

1. In your Fluent Form settings, set up a webhook integration
2. Set the webhook URL to `https://your-render-app.onrender.com/webhook`
3. Configure the webhook to send form data as JSON
4. Map the form fields to the expected format in `app.py`

### TextMagic Setup

1. Log in to your TextMagic dashboard
2. Go to Settings > Webhooks
3. Add a new webhook with these settings:
   - Webhook URL: `https://your-render-app.onrender.com/incoming-sms`
   - Webhook Type: Inbound message
   - HTTP Method: POST
   - Format: JSON
   - Enabled: Yes

## How It Works

1. When a form is submitted, the webhook receives the job details
2. The system looks up providers in the specified location from Google Sheets
3. It sends an SMS to the first provider with the job details
4. The provider can respond with "ACCEPT" or "DECLINE"
5. If declined, the system moves to the next provider in the list
6. Once accepted, the system stops notifying other providers

## Development

To run locally:

```bash
export FLASK_APP=app.py
export FLASK_ENV=development
flask run
```

## License

MIT
