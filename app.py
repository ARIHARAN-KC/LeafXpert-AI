from flask import Flask, render_template, request, jsonify
import os
import torch
from torchvision import transforms
from PIL import Image
import torchvision.models as models
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

# ===============================
# LOAD ENV VARIABLES
# ===============================
load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if not OPENROUTER_API_KEY:
    raise ValueError("OPENROUTER_API_KEY not found in .env")

# ===============================
# OpenRouter Client
# ===============================
router_client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1"
)

# ===============================
# Load CSV
# ===============================
disease_info = pd.read_csv('Model_assest/disease_info.csv')

# ===============================
# Device Setup
# ===============================
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

model = models.resnet18(weights=None)
model.fc = torch.nn.Linear(model.fc.in_features, 38)

model.load_state_dict(torch.load('Model_assest/model.pth', map_location=device))
model.to(device)
model.eval()

# ===============================
# Image Transform
# ===============================
transform = transforms.Compose([
    transforms.Resize(256),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize(
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225]
    )
])

# ===============================
# Prediction Function
# ===============================
def prediction(image_path):
    image = Image.open(image_path).convert("RGB")
    image = transform(image).unsqueeze(0).to(device)

    with torch.no_grad():
        output = model(image)
        output = output.cpu().numpy()
        index = np.argmax(output)

    return index


# ==========================================================
# LANGUAGE DETECTION (NEW - STRICT CONTROL)
# ==========================================================
def detect_language(text):
    # Tamil Unicode range
    if any('\u0B80' <= char <= '\u0BFF' for char in text):
        return "Tamil"

    # Hindi (Devanagari) Unicode range
    if any('\u0900' <= char <= '\u097F' for char in text):
        return "Hindi"

    # Default English
    return "English"


# ===============================
# GPT Function (UPDATED)
# ===============================
def ask_ai(prompt):
    try:
        language = detect_language(prompt)

        response = router_client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": f"""
You are an agricultural plant disease expert.

STRICT RULES:
- If Language is Tamil → Respond ONLY in Tamil.
- If Language is Hindi → Respond ONLY in Hindi.
- If Language is English → Respond ONLY in English.
- DO NOT translate unless asked.
- DO NOT mix languages.
- DO NOT respond in Spanish.
- Keep explanation simple for farmers.
Language: {language}
"""
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.5
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"AI Error: {str(e)}"


# ===============================
# Flask App
# ===============================
app = Flask(__name__)

UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ===============================
# Home
# ===============================
@app.route('/', methods=['GET', 'POST'])
def home():
    return render_template('home.html')

# ===============================
# AI Detect Page
# ===============================
@app.route('/index')
def ai_detect_page():
    return render_template('index.html')

# ===============================
# Image Submission
# ===============================
@app.route('/submit', methods=['POST'])
def submit():
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'})

    image = request.files['image']

    if image.filename == '':
        return jsonify({'error': 'Empty filename'})

    file_path = os.path.join(UPLOAD_FOLDER, image.filename)
    image.save(file_path)

    pred = prediction(file_path)

    title = disease_info['disease_name'][pred]
    description = disease_info['description'][pred]
    possible_step = disease_info['Possible Steps'][pred]
    ai_summary = ask_ai(
        f"The plant has {title}. Give treatment and prevention."
    )

    return render_template('submit.html', data={
        'prediction': title,
        'image': '/' + file_path,
        'description': description,
        'possible_step': possible_step,
        'ai_summary': ai_summary
    })

# ===============================
# Chatbot
# ===============================
@app.route('/response', methods=['GET', 'POST'])
def response():
    if request.method == "POST":
        query = request.form.get('text')
        answer = ask_ai(query)

        return render_template('chatbot.html', resp={
            "query": query,
            "answer": answer
        })

    return render_template('chatbot.html')

# ===============================
# Voice (Browser Text Based)
# ===============================
@app.route('/voice-query', methods=['POST'])
def voice_query():
    data = request.json
    user_text = data.get("text")

    if not user_text:
        return jsonify({"error": "No text received"}), 400

    ai_response = ask_ai(user_text)

    return jsonify({
        "query": user_text,
        "answer": ai_response
    })

@app.route('/voice')
def voice_page():
    return render_template('voice.html')

# ===============================
# Learn More
# ===============================
@app.route('/learnmore')
def learnmore():
    return render_template('learnmore.html')

if __name__ == '__main__':
    app.run(debug=True)