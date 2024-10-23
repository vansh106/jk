import os
import google.auth
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# Function to append data to a Google Sheet
def append_to_gsheet(data, sheet_id, range_name, service_account_file):
    """
    Appends data to a Google Sheet.

    :param data: 2D list where each inner list is a row of data to append
    :param sheet_id: The Google Sheet ID
    :param range_name: The range to which the data should be appended (e.g., 'Sheet1!A:Z')
    :param service_account_file: Path to the service account JSON key file
    """
    
    # Define the scope and credentials
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    
    # Create credentials from the service account file
    creds = Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
    
    # Build the Sheets API service
    service = build('sheets', 'v4', credentials=creds)
    
    # Define the resource body for appending the data
    body = {
        'values': data
    }
    
    # Call the Sheets API to append the data
    request = service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=range_name,
        valueInputOption='RAW',  # Use RAW or USER_ENTERED based on your needs
        insertDataOption='INSERT_ROWS',  # Insert new rows
        body=body
    )
    
    # Execute the request and return the response
    response = request.execute()
    
    # Print response (for debugging)
    print(f'Data appended successfully: {response}')
    
    return response