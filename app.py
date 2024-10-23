from flask import Flask, request, jsonify, send_from_directory
from rq import Queue
from redis import Redis
from rq.worker import Worker
from datetime import datetime
import os
import base64
import cv2
import warnings
import uuid
from tasks import process_images_task, preprocess_image, add_task, update_task, remove_completed_tasks, load_tasks

# Add this near the top of your app.py file, before initializing Redis or RQ
os.environ['OBJC_DISABLE_INITIALIZE_FORK_SAFETY'] = 'YES'

app = Flask(__name__)
warnings.filterwarnings("ignore", category=UserWarning, module="urllib3")
# Initialize Redis connection
redis_conn = Redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379'))
q = Queue(connection=redis_conn, is_async=True, default_timeout=3600)

# Path for storing temporary images
TEMP_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'temp')

def run_shell_command(command):
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True)
    return result.stdout.strip(), result.stderr.strip()

# Run pwd and ls commands
current_directory, pwd_error = run_shell_command('pwd')
files_list, ls_error = run_shell_command('ls -la')

# Print the results to the console (or handle errors if needed)
print("Current Directory:", current_directory)
if pwd_error:
    print("Error running pwd:", pwd_error)

print("Files and Directories:\n", files_list)
if ls_error:
    print("Error running ls:", ls_error)

def save_base64_image(base64_str, filename):
    image_data = base64.b64decode(base64_str.split(',')[1])
    image_path = os.path.join(TEMP_FOLDER, filename)
    with open(image_path, 'wb') as f:
        f.write(image_data)
    return image_path


@app.route('/')
def index():
    return send_from_directory('frontend', 'index.html')


@app.route('/task-list')
def tasks():
    return send_from_directory('frontend', 'tasks.html')


@app.route('/preprocess', methods=['POST'])
def preprocess():
    data = request.json
    image_base64 = data.get('image')
    should_preprocess = data.get('preprocess', False)

    if image_base64:
        image_filename = f"uploaded_image_{datetime.now().timestamp()}.png"
        image_path = save_base64_image(image_base64, image_filename)

        if should_preprocess:
            processed_image = preprocess_image(image_path)
        else:
            with open(image_path, "rb") as image_file:
                processed_image = image_file.read()

        processed_image_base64 = 'data:image/png;base64,' + \
            base64.b64encode(processed_image).decode('utf-8')

        return jsonify({'processed_image': processed_image_base64}), 200

    return jsonify({'error': 'No image provided'}), 400


@app.route('/submit-task', methods=['POST'])
def submit_task():
    data = request.json
    images_base64 = data.get('images')
    series = data.get('series')
    scan_type = data.get('scan_type')  # Get the selected scan type

    if images_base64 and isinstance(images_base64, list):
        image_paths = []
        time_str = datetime.now().strftime('%H:%M:%S')
        date_str = datetime.now().strftime('%Y-%m-%d')

        for idx, image_base64 in enumerate(images_base64):
            image_filename = f"""processed_image_{
                datetime.now().timestamp()}_{idx}.png"""
            image_path = save_base64_image(image_base64, image_filename)
            image_paths.append(image_path)

        bill_no = get_next_bill_no()

        # Create a task entry
        task = {
            'job_id': str(uuid.uuid4()),  # Generate a unique ID
            'bill_no': bill_no,
            'time': time_str,
            'date': date_str,
            'state': 'Queued',
            'progress': 'Queued',
            'result': '',
            'error': '',
            'image_paths': image_paths,
            'series': series,
            'scan_type': scan_type  # Store the scan type
        }
        add_task(task)

        # Enqueue the task with RQ
        job = q.enqueue(
            # Pass scan_type
            process_images_task, task['job_id'], image_paths, bill_no, time_str, date_str, series, scan_type)

        return jsonify({'job_id': task['job_id']}), 202

    return jsonify({'error': 'No images provided'}), 400


@app.route('/task-status/<job_id>', methods=['GET'])
def task_status(job_id):
    job = q.fetch_job(job_id)
    if job is None:
        return jsonify({'error': 'No such job'}), 404

    status = {
        'job_id': job.id,
        'status': job.get_status(),
        'result': job.result,
        'enqueued_at': job.enqueued_at.isoformat() if job.enqueued_at else None,
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'ended_at': job.ended_at.isoformat() if job.ended_at else None,
    }
    return jsonify(status)


@app.route('/tasks', methods=['GET'])
def get_tasks():
    show_today_only = request.args.get('today', 'false').lower() == 'true'
    current_date = datetime.now().strftime('%Y-%m-%d')

    tasks = load_tasks()

    if show_today_only:
        tasks = [task for task in tasks if task.get('date') == current_date]

    # Sort tasks by Bill No. (descending order)
    tasks.sort(key=lambda x: x.get('bill_no', 0), reverse=True)

    return jsonify(tasks)


@app.route('/<path:filename>')
def serve_static_files(filename):
    return send_from_directory('frontend', filename)


def get_next_bill_no():
    current_date = datetime.now().strftime('%Y-%m-%d')
    bill_no_key = f"bill_no:{current_date}"
    if not redis_conn.exists(bill_no_key):
        redis_conn.set(bill_no_key, 1)
    else:
        redis_conn.incr(bill_no_key)
    return int(redis_conn.get(bill_no_key))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
