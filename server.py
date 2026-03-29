import os
import time
import base64
import requests
import threading
from flask import Flask, request, jsonify, render_template
from playwright.sync_api import sync_playwright

app = Flask(__name__)

# Configuración de carpetas
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(BASE_DIR, 'static', 'images')
VIDEO_DIR = os.path.join(BASE_DIR, 'static', 'videos')
for d in [IMAGE_DIR, VIDEO_DIR]: os.makedirs(d, exist_ok=True)

status = {"state": "idle", "url": None, "type": None}

# --- FILTROS DE ADBLOCK ---
AD_DOMAINS = [
    "google-analytics", "doubleclick", "adservice", "popads", 
    "adskeeper", "coinhive", "facebook.net", "googlesyndication"
]

def apply_adblock(route):
    if any(ad in route.request.url for ad in AD_DOMAINS):
        return route.abort()
    return route.continue_()

# --- LÓGICA DE GENERACIÓN ---
def run_automation(prompt, mode):
    global status
    status.update({"state": "processing", "type": mode, "url": None})
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True) # Pon True para que sea invisible
            context = browser.new_context()
            page = context.new_page()
            
            # Activar Adblock
            page.route("**/*", apply_adblock)

            if mode == "image":
                page.goto("https://freegen.app/", wait_until="networkidle")
                page.fill("textarea", prompt)
                page.click("button:has-text('Generate')")
                time.sleep(0.5); page.click("button:has-text('Generate')")
                
                # Extracción Base64 mediante JS
                page.wait_for_timeout(10000)
                img_data = page.evaluate("""() => {
                    const target = Array.from(document.querySelectorAll('img'))
                        .find(i => i.naturalWidth > 300 && !i.src.includes('logo'));
                    return target ? target.src : null;
                }""")
                
                if img_data:
                    filename = f"img_{int(time.time())}.png"
                    path = os.path.join(IMAGE_DIR, filename)
                    if img_data.startswith("data:"):
                        with open(path, "wb") as f: f.write(base64.b64decode(img_data.split(",")[1]))
                    else:
                        with open(path, "wb") as f: f.write(requests.get(img_data).content)
                    status.update({"state": "done", "url": f"/static/images/{filename}"})

            elif mode == "video":
                page.goto("https://veoaifree.com/grok-ai-video-generator/", wait_until="networkidle")
                page.fill("textarea", prompt)
                page.click("button:has-text('Generate')")
                
                print("Esperando video...")
                # Buscamos el tag video o un link .mp4 (esperamos hasta 3 min)
                video_el = page.wait_for_selector("video, video source, a[href$='.mp4']", timeout=180000)
                video_src = video_el.get_attribute("src") or video_el.get_attribute("href")
                
                if video_src:
                    filename = f"vid_{int(time.time())}.mp4"
                    path = os.path.join(VIDEO_DIR, filename)
                    res = requests.get(video_src, stream=True)
                    with open(path, "wb") as f:
                        for chunk in res.iter_content(1024): f.write(chunk)
                    status.update({"state": "done", "url": f"/static/videos/{filename}"})

            browser.close()
    except Exception as e:
        print(f"Error: {e}")
        status.update({"state": "error", "error": str(e)})

# --- RUTAS FLASK ---
@app.route("/generate", methods=["POST"])
def generate():
    data = request.json
    threading.Thread(target=run_automation, args=(data['prompt'], data['mode'])).start()
    return jsonify({"status": "started"})

@app.route("/status")
def get_status():
    history = []
    # Leer imágenes
    for f in os.listdir(IMAGE_DIR):
        history.append({"url": f"/static/images/{f}", "type": "image", "t": os.path.getctime(os.path.join(IMAGE_DIR, f))})
    # Leer videos
    for f in os.listdir(VIDEO_DIR):
        history.append({"url": f"/static/videos/{f}", "type": "video", "t": os.path.getctime(os.path.join(VIDEO_DIR, f))})
    
    history.sort(key=lambda x: x['t'], reverse=True)
    return jsonify({**status, "history": history})

@app.route("/")
def index(): return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True, port=5000)