import warnings
import os
import cv2
import base64
import json
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import requests
from openai import OpenAI
from dotenv import load_dotenv
import threading
from sheets import append_to_gsheet


SERVICE_ACCOUNT_FILE = 'credentials.json'

# Create credentials from the service account file
# The ID of the Google Sheet (found in the sheet URL)
SPREADSHEET_ID = '1nAZ6i2YnrwIJxy7qrWiTmWIXbOLfV7S2FIOpuUt0NuA'

# The range where you want to append the data
RANGE_NAME = 'Sheet1!A:Z'

load_dotenv()
warnings.filterwarnings("ignore", category=UserWarning, module="urllib3")

INVOICE_DB_PATH = "invoice.json"
TEMP_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'temp')
TASKS_FILE = os.path.join(os.path.dirname(
    os.path.abspath(__file__)), 'tasks.json')
OPEN_API_KEY = os.getenv('OPENAI_API_KEY')
MODEL = "gpt-4o"

client = OpenAI(api_key=OPEN_API_KEY)
tasks_lock = threading.Lock()

# Move task-related functions here


def load_tasks():
    if not os.path.exists(TASKS_FILE):
        return []
    with open(TASKS_FILE, 'r') as f:
        return json.load(f)


def save_tasks(tasks):
    with open(TASKS_FILE, 'w') as f:
        json.dump(tasks, f, indent=4)


def add_task(task):
    with tasks_lock:
        tasks = load_tasks()
        tasks.append(task)
        save_tasks(tasks)


def update_task(job_id, updates):
    with tasks_lock:
        tasks = load_tasks()
        for task in tasks:
            if task['job_id'] == job_id:
                task.update(updates)
                break
        save_tasks(tasks)


def remove_completed_tasks():
    with tasks_lock:
        tasks = load_tasks()
        tasks = [task for task in tasks if task['state']
                 not in ['Completed', 'Failure']]
        save_tasks(tasks)


def load_invoices():
    if not os.path.exists(INVOICE_DB_PATH):
        return []
    with open(INVOICE_DB_PATH, 'r') as f:
        try:
            invoices = json.load(f)
        except json.JSONDecodeError:
            invoices = []
    return invoices


def save_invoices(invoices):
    with open(INVOICE_DB_PATH, 'w') as f:
        json.dump(invoices, f, indent=4)


def preprocess_image(image_path):
    image = cv2.imread(image_path)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(
        gray, 180, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    blurred = cv2.medianBlur(thresh, 3)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    processed_with_timestamp = append_timestamp(
        blurred, f"Processed: {timestamp}")
    _, buffer = cv2.imencode('.png', processed_with_timestamp)
    return buffer.tobytes()


def append_timestamp(image, text):
    pil_image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_image)
    font = ImageFont.load_default()
    text_position = (10, 10)
    draw.text(text_position, text, font=font, fill=(255, 255, 255))
    return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)


def extract_table_from_image(image_paths, prompt):
    messages = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Analyze these images and extract the information as per the instructions."}
            ]
        }
    ]

    for image_path in image_paths.split(','):
        with open(image_path.strip(), "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')
        messages[1]["content"].append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
        })
    print("Sending messages to GPT")
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        max_tokens=2500
    )
    return response.choices[0].message.content


def prepare_bills_sheets_data(invoice_data):
    sheets_data = []

    for product in invoice_data.get("products", []):
        try:
            quantity = float(product.get("quantity", "0").split()[
                             0].replace(',', ''))
            rate = float(product.get("rate", "0").replace(',', ''))
            amount = float(product.get("amount", "0").replace(',', ''))
        except ValueError:
            quantity, rate, amount = 0, 0, 0

        calculated_amount = quantity * rate
        amount_str = product.get("amount", "0")
        if abs(calculated_amount - amount) > 0.01:
            amount_str += "_wrong"

        product_data = {
            "Series": invoice_data.get("series", "A1"),
            "date": invoice_data.get("date", ""),
            "INVOICE NO": invoice_data.get("invoice_no", ""),
            "Purchase Type": "L/GST-18%",
            "party name": invoice_data.get("name", "") if len(sheets_data) == 0 else "",
            "mat.centre": "",
            "item name": product.get("product_details", ""),
            "qty": product.get("quantity", "").split()[0] if product.get("quantity") else "0",
            "unit": product.get("quantity", "").split()[1] if product.get("quantity") else "",
            "price": product.get("rate", 0),
            "amount": amount_str,
            "NARRATION": "",
            "TRANSACTION TYPE": "Purchase",
            "REASON": "",
            "TRANSPORTER NAME": invoice_data.get("transporter_name", ""),
            "VEHICLE NO": invoice_data.get("vehicle_no", ""),
            "EWAY BILL NO": invoice_data.get("eway_bill_no", ""),
            "LR NO": invoice_data.get("lr_no", ""),
            "IGST": invoice_data.get("igst", ""),
            "CGST": invoice_data.get("cgst", ""),
            "SGST": invoice_data.get("sgst", ""),
            "Discount": 0,
            "CUTTING CHARGES.+ New": 0,
            "PF": 0,
            "TRANSPORT": "",
            "TAXABLE AMT": invoice_data.get("taxable_amount", ""),
            "Rounded Off (-)": invoice_data.get("rounded_off_-", ""),
            "Rounded Off (+)": invoice_data.get("rounded_off_+", ""),
            "FINAL AMOUNT": product.get("amount", 0)
        }

        try:
            gst_percentage = float(product.get("gst", "0").strip('%')) / 100
        except ValueError:
            gst_percentage = 0

        if gst_percentage > 0:
            taxable_amount = float(
                str(product.get("amount", "0")).replace(',', ''))
            gst_amount = taxable_amount * gst_percentage
            product_data["TAXABLE AMT"] = taxable_amount
            product_data["CGST"] = gst_amount / 2
            product_data["SGST"] = gst_amount / 2

        push_to_sheets(product_data, os.getenv('BILLS_SHEETS_API_URL'))
        sheets_data.append(product_data)

    return sheets_data


def push_to_sheets(data, sheet_url):
    SHEETS_API_URL = sheet_url
    headers = {'Content-Type': 'application/json'}
    response = requests.post(SHEETS_API_URL, json=data, headers=headers)
    print("GSHEETS", data, response.content)
    if response.status_code != 200:
        raise Exception(
            f"Failed to push data to Google Sheets: {response.text}")


def process_images_task(job_id, image_paths, bill_no, time_str, date_str, series, scan_type):
    try:
        update_task(job_id, {'state': 'Processing',
                    'progress': 'Starting processing on images'})

        combined_image_paths = ','.join(image_paths)

        update_task(job_id, {'progress': 'Processing images'})
        # Adjust the prompt based on scan type
        if scan_type == 'visiting_cards':
            prompt = VCPrompt
            # Different Google Sheets link
            SHEETS_API_URL = os.getenv('VISITING_CARDS_SHEETS_API_URL')
            gpt_output = extract_table_from_image(
                combined_image_paths, prompt)  # Pass the prompt
            update_task(job_id, {'progress': 'Processing completed'})

            result = {'gpt_output': gpt_output}
            print("GPT OUTPUT", result)
            # Parse the JSON data
            visiting_card_data = json.loads(gpt_output)

# Prepare the data to append (as a list of rows)
            data_to_append = [[
                visiting_card_data.get("Company"),
                visiting_card_data.get("Name"),
                visiting_card_data.get("Designation"),
                visiting_card_data.get("Email"),
                visiting_card_data.get("Phone")
            ]]

# Append data to Google Sheets
            append_to_gsheet(data_to_append, SPREADSHEET_ID, RANGE_NAME, SERVICE_ACCOUNT_FILE)
            # Process visiting card data
            # push_to_sheets(visiting_card_data, os.getenv(
            #     'VISITING_CARDS_SHEETS_API_URL'))

            # prepare_visiting_cards_data(visiting_card_data)

            update_task(job_id, {
                'state': 'Completed',
                'progress': 'Completed',
                # Assuming name is a key in visiting card data
                'result': visiting_card_data['Name'],
                'error': ''
            })
            print("processing completed")

            remove_completed_tasks()
            return result
        else:
            prompt = BillPrompt
            # Original Google Sheets link
            SHEETS_API_URL = os.getenv('BILLS_SHEETS_API_URL')

            gpt_output = extract_table_from_image(
                combined_image_paths, prompt)  # Pass the prompt
            update_task(job_id, {'progress': 'Processing completed'})

            result = {'gpt_output': gpt_output}
            invoice_data = json.loads(gpt_output)
            if scan_type != 'visiting_cards':
                invoice_data['series'] = series
                invoices = load_invoices()
                print("sheets processing starting")

                existing_invoice_nos = {
                    invoice['invoice_no'] for invoice in invoices}
                if invoice_data['invoice_no'] in existing_invoice_nos:
                    update_task(
                        job_id, {'progress': 'Invoice already present'})
                else:
                    invoices.append(invoice_data)
                    save_invoices(invoices)
                    sheets_data = prepare_bills_sheets_data(invoice_data)
                    print("sheets processing completed")

                    update_task(
                        job_id, {'progress': 'Data pushed to Google Sheets'})

                update_task(job_id, {
                    'state': 'Completed',
                    'progress': 'Completed',
                    'result': invoice_data['invoice_no'],
                    'error': ''
                })
                print("processing completed")

                remove_completed_tasks()
                return result

    except Exception as e:
        update_task(job_id, {
            'state': 'Failure',
            'progress': 'Failed',
            'result': '',
            'error': str(e)
        })
        remove_completed_tasks()
        raise


def ensure_temp_folder():
    if not os.path.exists(TEMP_FOLDER):
        os.makedirs(TEMP_FOLDER)


ensure_temp_folder()

BillPrompt = """
    You are an AI assistant specialized in extracting structured information from images. Your task is to analyze the following image(s) and create a JSON object with the following structure:
    {
        "name": "",
        "invoice_no": "",
        "GSTIN": "",
        "date": "",
        "total_amount": "",
        "transporter_name": "",
        "vehicle_no": "",
        "eway_bill_no": "",
        "lr_no": "",
        "igst": "",
        "cgst": "",
        "sgst": "",
        "taxable_amount": "",
        "rounded_off_-": "",
        "rounded_off_+": "",
        "products": [
            {
                "product_details": "",
                "hsn_code": "",
                "rate": "",
                "gst": "",
                "nos": "",
                "quantity": "",
                "unit": "",
                "amount": ""
            }
        ]
    }
    Instructions:
    - Carefully analyze the image(s) provided.
    - Identify information related to the company name, date, invoice number, GSTIN, total amount, TRANSPORTER NAME, VEHICLE NO, EWAY BILL NO, LR NO, IGST, CGST, SGST, TAXABLE AMT.
    - For each product mentioned, extract details including product description, HSN Code, Rate, GST, NOS (if applicable), quantity, amount.
    - Organize this information into the JSON format specified above.
    - Quantity should always be in "value unit" format. For example - 325.5 Kgs or 32.5 T 
    - If any information is missing or unclear, use "" as the value.
    - do not do any mathematical calculations, just extract the information.
    - Ensure that the "products" array contains an object for each product mentioned in the image(s).
    PLEASE DO NOT WRITE ANYTHING ELSE APART FROM THE JSON OBJECT

    Please provide the extracted information in the JSON format specified above BUT DONT PROVIDE JSON CODE, I WANT JSON TEXT.
    """

VCPrompt = """
    You are an AI assistant specialized in extracting structured information from visiting card images. Your task is to analyze the following image(s) and create a JSON object with the following structure:
    {
        "Name": "",
        "Phone": "",
        "Address": "",
        "Email": "",
        "Company": "",
        "Designation": "",
    }
    Instructions:
    - Carefully analyze the image(s) provided.
    - Organize this information into the JSON format specified above.
    - If any information is missing or unclear, use "" as the value.
    PLEASE DO NOT WRITE ANYTHING ELSE APART FROM THE JSON OBJECT

    Please provide the extracted information in the JSON format specified above BUT DONT PROVIDE JSON CODE, I WANT JSON TEXT.
    """


def prepare_visiting_cards_data(visiting_card_data):
    visiting_cards_data = []

    # Extracting relevant fields from the visiting card data
    card_data = {
        "Name": visiting_card_data.get("Name", ""),
        "Phone": visiting_card_data.get("Phone", ""),
        "Address": visiting_card_data.get("Address", ""),
        "Email": visiting_card_data.get("Email", ""),
        "Company": visiting_card_data.get("Company", ""),
        "Designation": visiting_card_data.get("Designation", ""),
    }

    # Append the processed card data to the list
    visiting_cards_data.append(card_data)

    # Push the visiting card data to the sheets
    push_to_sheets(card_data, os.getenv('VISITING_CARDS_SHEETS_API_URL'))

    return visiting_cards_data
