# this shit was NOT fun to do bruh

from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
from celery import Celery
import os
import re
import logging
from flask_sqlalchemy import SQLAlchemy
import aiofiles
from concurrent.futures import ThreadPoolExecutor

# Configure Flask app
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads/'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize Celery
celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# Define models
class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_number = db.Column(db.Integer, nullable=False)
    event_name = db.Column(db.String(120), nullable=False)
    event_date = db.Column(db.String(50), nullable=True)

class Participant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_number = db.Column(db.Integer, nullable=False)
    swimmer_id = db.Column(db.String(120), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    team = db.Column(db.String(100), nullable=True)
    seed_time = db.Column(db.String(50), nullable=True)
    final_time = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(20))

# Setup logging
logging.basicConfig(filename='hytek_parser.log', level=logging.ERROR, format='%(asctime)s:%(levelname)s:%(message)s')

# Parser class
class HyTekParser:
    def __init__(self, content):
        self.content = content

    def parse_section(self, pattern, section_name):
        try:
            matches = re.finditer(pattern, self.content, re.MULTILINE)
            return [match.groups() for match in matches]
        except Exception as e:
            logging.error(f"Failed to parse {section_name}: {str(e)}")
            return []  # Continue with other sections

# File upload route
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return "No file part", 400
    file = request.files['file']
    if file.filename == '':
        return "No selected file", 400
    if file:
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        parse_hytek_file.delay(file_path)
        return "File uploaded and parsing initiated", 202

# Celery task
@celery.task
def parse_hytek_file(file_path):
    asyncio.run(process_file(file_path))

async def process_file(file_path):
    async with aiofiles.open(file_path, 'r') as file:
        content = await file.read()
    process_content(content)

def process_content(content):
    parser = HyTekParser(content)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(parser.parse_section, [
            (r'^C1(\d{2})(\d{4})(\d{4})(.*)(\d{1})(\d{1})(\d{1})(\d{1})(\d{2}\/\d{2}\/\d{4})', "Events"),
            (r'^D3(\d{4})(\d{4})(.*)([A-Z]{2})(\d{2}:\d{2}.\d{2})(\d{2}:\d{2}.\d{2})([A-Z]+)', "Participants")
        ]))
        events, participants = results
        store_data(events, participants)

def store_data(events, participants):
    try:
        for event in events:
            new_event = Event(event_number=int(event[1]), event_name=event[3], event_date=event[8])
            db.session.add(new_event)
        for participant in participants:
            new_participant = Participant(
                event_number=int(participant[0]), 
                swimmer_id=participant[1], 
                name=participant[2],
                team=participant[3],
                seed_time=participant[4],
                final_time=participant[5],
                status=participant[6])
            db.session.add(new_participant)
        db.session.commit()
    except Exception as e:
        logging.error(f"Failed to store data: {str(e)}")

if __name__ == '__main__':
    db.create_all()
    app.run(debug=True)
