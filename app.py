from flask import Flask, render_template, request, jsonify, url_for
import os
from werkzeug.utils import secure_filename
from ultralytics import YOLO
import time
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['RUNS_FOLDER'] = 'static/runs'
app.config['DATABASE'] = 'ppe_database.db'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['RUNS_FOLDER'], exist_ok=True)

def init_db():
    with sqlite3.connect(app.config['DATABASE']) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT,
                result_url TEXT,
                timestamp DATETIME,
                helmet_count INTEGER,
                vest_count INTEGER,
                status TEXT
            )
        ''')
        conn.commit()

init_db()

# Load the custom trained PPE detection model
model = YOLO('runs/detect/runs/detect/train/ppe_model/weights/best.pt')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/detect-page')
def detect_page():
    return render_template('detect.html')

@app.route('/detect', methods=['POST'])
def detect():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'})
        
    if file:
        filename = secure_filename(file.filename)
        timestamp = str(int(time.time()))
        unique_filename = f"{timestamp}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)
        
        # Run inference
        results = model.predict(source=filepath)
        
        # Save the result image manually to ensure correct path
        out_dir = os.path.join(app.config['RUNS_FOLDER'], timestamp)
        os.makedirs(out_dir, exist_ok=True)
        out_filepath = os.path.join(out_dir, unique_filename)
        results[0].save(filename=out_filepath)
        
        # Generate the URL for the frontend
        result_url = url_for('static', filename=f"runs/{timestamp}/{unique_filename}")
        
        # Extract metadata (bounding boxes, classes)
        detections = []
        helmet_count = 0
        vest_count = 0
        
        for r in results:
            for box in r.boxes:
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                cls_name = model.names[cls_id]
                detections.append({'class': cls_name, 'confidence': conf})
                if cls_name.lower() == 'helmet':
                    helmet_count += 1
                elif cls_name.lower() == 'vest':
                    vest_count += 1
                    
        # Determine status
        # Compliant if at least 1 helmet and 1 vest is detected (simple rule for now)
        status = 'Compliant' if (helmet_count > 0 and vest_count > 0) else 'Non-Compliant'
        
        # Save to database
        with sqlite3.connect(app.config['DATABASE']) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO detections (filename, result_url, timestamp, helmet_count, vest_count, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (filename, result_url, datetime.now(), helmet_count, vest_count, status))
            conn.commit()
                
        return jsonify({
            'success': True,
            'result_url': result_url,
            'detections': detections,
            'helmet_count': helmet_count,
            'vest_count': vest_count,
            'status': status
        })

@app.route('/api/dashboard')
def dashboard_api():
    try:
        with sqlite3.connect(app.config['DATABASE']) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get stats
            cursor.execute("SELECT COUNT(*) as total FROM detections")
            total_scans = cursor.fetchone()['total']
            
            cursor.execute("SELECT COUNT(*) as compliant FROM detections WHERE status = 'Compliant'")
            compliant_scans = cursor.fetchone()['compliant']
            
            non_compliant = total_scans - compliant_scans
            compliance_rate = round((compliant_scans / total_scans * 100) if total_scans > 0 else 0)
            
            # Get recent history
            cursor.execute("SELECT * FROM detections ORDER BY timestamp DESC LIMIT 10")
            history = [dict(row) for row in cursor.fetchall()]
            
            return jsonify({
                'success': True,
                'total_scans': total_scans,
                'compliance_rate': compliance_rate,
                'non_compliant': non_compliant,
                'history': history
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
