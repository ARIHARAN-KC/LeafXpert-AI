# ==============================
# LOAD ENV FIRST (VERY IMPORTANT)
# ==============================
import os
from dotenv import load_dotenv

load_dotenv()

# ==============================
# NORMAL IMPORTS
# ==============================
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
import torch
from torchvision import transforms
from PIL import Image
import torchvision.models as models
import pandas as pd
import numpy as np
from openai import OpenAI

# NEW IMPORTS (Authentication)
from config import Config
from models import db, User
from flask_login import LoginManager, login_user, login_required, logout_user, current_user

# ==============================
# OPENROUTER KEY
# ==============================
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if not OPENROUTER_API_KEY:
    raise ValueError("OPENROUTER_API_KEY not found in .env")

# ==============================
# FLASK APP
# ==============================
app = Flask(__name__)
app.config.from_object(Config)

# Initialize DB
db.init_app(app)

# Initialize Login Manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# Create tables (safe if already exists)
with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==============================
# OPENROUTER CLIENT
# ==============================
router_client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1"
)

# ==============================
# LOAD DATA + MODEL
# ==============================
disease_info = pd.read_csv('Model_assest/disease_info.csv')

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

model = models.resnet18(weights=None)
model.fc = torch.nn.Linear(model.fc.in_features, 38)

model.load_state_dict(torch.load('Model_assest/model.pth', map_location=device))
model.to(device)
model.eval()

transform = transforms.Compose([
    transforms.Resize(256),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize(
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225]
    )
])

# ==============================
# PREDICTION FUNCTION
# ==============================
def prediction(image_path):
    image = Image.open(image_path).convert("RGB")
    image = transform(image).unsqueeze(0).to(device)

    with torch.no_grad():
        output = model(image)
        output = output.cpu().numpy()
        index = np.argmax(output)

    return index

# ==============================
# LANGUAGE DETECTION
# ==============================
def detect_language(text):
    if any('\u0B80' <= char <= '\u0BFF' for char in text):
        return "Tamil"
    if any('\u0900' <= char <= '\u097F' for char in text):
        return "Hindi"
    return "English"

# ==============================
# AI FUNCTION
# ==============================
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
- DO NOT mix languages.
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

# ==============================
# AUTH ROUTES
# ==============================
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('ai_detect_page'))

    if request.method == "POST":
        username = request.form.get("username").strip()
        email = request.form.get("email").strip()
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")

        # Validation
        if not username or not email or not password:
            flash("All fields are required", "danger")
            return redirect(url_for('signup'))

        if password != confirm_password:
            flash("Passwords do not match", "danger")
            return redirect(url_for('signup'))

        if User.query.filter_by(email=email).first():
            flash("Email already registered", "warning")
            return redirect(url_for('signup'))

        if User.query.filter_by(username=username).first():
            flash("Username already taken", "warning")
            return redirect(url_for('signup'))

        new_user = User(username=username, email=email)
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        flash("Account created successfully! Please login.", "success")
        return redirect(url_for('login'))

    return render_template("signup.html")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('ai_detect_page'))

    if request.method == "POST":
        email = request.form.get("email").strip()
        password = request.form.get("password")

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            login_user(user)
            flash("Login successful!", "success")
            return redirect(url_for('ai_detect_page'))
        else:
            flash("Invalid email or password", "danger")
            return redirect(url_for('login'))

    return render_template("login.html")


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for('home'))

# ==============================
# MAIN ROUTES
# ==============================
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/index')
@login_required
def ai_detect_page():
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
@login_required
def submit():
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'})

    image = request.files['image']

    if image.filename == '':
        return jsonify({'error': 'Empty filename'})

    UPLOAD_FOLDER = 'static/uploads'
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

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

# ==============================
# CHATBOT
# ==============================
@app.route('/response', methods=['GET', 'POST'])
@login_required
def response():
    if request.method == "POST":
        query = request.form.get('text')
        answer = ask_ai(query)

        return render_template('chatbot.html', resp={
            "query": query,
            "answer": answer
        })

    return render_template('chatbot.html')

# ==============================
# VOICE
# ==============================
@app.route('/voice-query', methods=['POST'])
@login_required
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
@login_required
def voice_page():
    return render_template('voice.html')

@app.route('/learnmore')
@login_required
def learnmore():
    return render_template('learnmore.html')

# ==============================
# RUN APP
# ==============================
if __name__ == '__main__':
    app.run(debug=True)