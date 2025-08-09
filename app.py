from flask import Flask, request, render_template_string, send_file, flash, redirect, url_for, jsonify
import os
import subprocess
from PIL import Image, ImageOps
import tempfile
import uuid
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-in-production')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Use /tmp for cloud platforms, local uploads for development
UPLOAD_FOLDER = '/tmp/uploads' if os.path.exists('/tmp') else 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def find_potrace():
    """Try to find potrace executable"""
    possible_paths = [
        'potrace',
        '/usr/bin/potrace',
        '/usr/local/bin/potrace',
        r'C:\Users\Angel\Downloads\potrace-1.16.win64\potrace-1.16.win64\potrace.exe',
        r'C:\tools\potrace\potrace.exe',
    ]
    
    for path in possible_paths:
        try:
            result = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return path
        except:
            continue
    return None

def image_to_svg_simple(image_path, output_path, threshold=128):
    """
    Fallback SVG conversion using only PIL (no external dependencies)
    Creates a pixelated but functional SVG
    """
    try:
        with Image.open(image_path) as img:
            # Convert to grayscale and apply threshold
            if img.mode != 'L':
                img = img.convert('L')
            
            # Resize for performance (increased for better quality)
            max_size = (600, 600)
            original_size = img.size
            if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
                img.thumbnail(max_size, Image.Resampling.LANCZOS)
            
            # Apply threshold with better edge detection
            threshold = 140  # Better threshold value
            img = img.point(lambda x: 255 if x > threshold else 0, mode='1')
            
            width, height = img.size
            scale_x = original_size[0] / width
            scale_y = original_size[1] / height
            
            # Create SVG header
            svg_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{original_size[0]}" height="{original_size[1]}" viewBox="0 0 {original_size[0]} {original_size[1]}">
<rect width="{original_size[0]}" height="{original_size[1]}" fill="white"/>
<g transform="scale({scale_x:.2f},{scale_y:.2f})">
'''
            
            # Convert pixels to rectangles (optimized for smaller file size)
            pixels = list(img.getdata())
            
            # Group adjacent pixels into larger rectangles
            processed = [[False] * width for _ in range(height)]
            
            for y in range(height):
                for x in range(width):
                    pixel_index = y * width + x
                    if (pixel_index < len(pixels) and 
                        pixels[pixel_index] == 0 and 
                        not processed[y][x]):
                        
                        # Find the largest rectangle starting from this point
                        rect_width = 1
                        rect_height = 1
                        
                        # Expand width
                        while (x + rect_width < width and 
                               (y * width + x + rect_width) < len(pixels) and
                               pixels[y * width + x + rect_width] == 0 and
                               not processed[y][x + rect_width]):
                            rect_width += 1
                        
                        # Try to expand height
                        can_expand_height = True
                        while (y + rect_height < height and can_expand_height):
                            for dx in range(rect_width):
                                pixel_idx = (y + rect_height) * width + x + dx
                                if (pixel_idx >= len(pixels) or 
                                    pixels[pixel_idx] != 0 or
                                    processed[y + rect_height][x + dx]):
                                    can_expand_height = False
                                    break
                            if can_expand_height:
                                rect_height += 1
                        
                        # Mark rectangle as processed
                        for dy in range(rect_height):
                            for dx in range(rect_width):
                                if y + dy < height and x + dx < width:
                                    processed[y + dy][x + dx] = True
                        
                        # Add rectangle to SVG
                        svg_content += f'<rect x="{x}" y="{y}" width="{rect_width}" height="{rect_height}" fill="black"/>\n'
            
            svg_content += '</g></svg>'
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(svg_content)
            
            return True, "Success"
    except Exception as e:
        return False, f"Error: {str(e)}"

def convert_image_to_svg(image_path, output_path):
    """
    Try potrace first, fall back to PIL-based conversion
    """
    potrace_path = find_potrace()
    
    # Try potrace if available (best quality)
    if potrace_path:
        try:
            temp_dir = tempfile.gettempdir()
            temp_pbm = os.path.join(temp_dir, f"temp_{uuid.uuid4()}.pbm")
            
            with Image.open(image_path) as img:
                if img.mode != 'L':
                    img = img.convert('L')
                img = img.point(lambda x: 255 if x > 128 else 0, mode='1')
                img.save(temp_pbm, format='PPM')
            
            cmd = [potrace_path, temp_pbm, '-s', '-o', output_path, '--tight']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if os.path.exists(temp_pbm):
                os.remove(temp_pbm)
            
            if result.returncode == 0:
                return True, "Success (High Quality)"
        except Exception as e:
            print(f"Potrace failed, falling back to PIL: {e}")
    
    # Fall back to PIL-based conversion
    return image_to_svg_simple(image_path, output_path)

@app.route('/')
def index():
    return render_template_string(TEMPLATE)

@app.route('/health')
def health():
    """Health check endpoint for hosting platforms"""
    return jsonify({
        'status': 'healthy',
        'message': 'SVG Tool by 3DTV is running',
        'potrace_available': find_potrace() is not None
    })

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash('No file selected')
        return redirect(url_for('index'))
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected')
        return redirect(url_for('index'))
    
    allowed_extensions = {'png', 'jpg', 'jpeg', 'bmp', 'tiff', 'tif', 'gif'}
    if not ('.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions):
        flash('Invalid file type. Please upload an image file.')
        return redirect(url_for('index'))
    
    try:
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        upload_path = os.path.join(UPLOAD_FOLDER, unique_filename)
        file.save(upload_path)
        
        svg_filename = f"{os.path.splitext(unique_filename)[0]}.svg"
        svg_path = os.path.join(UPLOAD_FOLDER, svg_filename)
        
        success, message = convert_image_to_svg(upload_path, svg_path)
        
        # Clean up uploaded file
        if os.path.exists(upload_path):
            os.remove(upload_path)
        
        if success and os.path.exists(svg_path):
            return send_file(
                svg_path, 
                as_attachment=True, 
                download_name=f"{os.path.splitext(filename)[0]}.svg",
                mimetype='image/svg+xml'
            )
        else:
            flash(f'Conversion failed: {message}')
            return redirect(url_for('index'))
            
    except Exception as e:
        flash(f'Upload failed: {str(e)}')
        return redirect(url_for('index'))

# Your existing beautiful HTML template
TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SVG Tool by 3DTV</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(-45deg, #667eea, #764ba2, #f093fb, #f5576c, #4facfe, #00f2fe);
            background-size: 400% 400%;
            animation: gradientFlow 12s ease infinite;
            min-height: 100vh;
            padding: 20px;
        }
        
        @keyframes gradientFlow {
            0% { background-position: 0% 50%; }
            25% { background-position: 100% 50%; }
            50% { background-position: 100% 100%; }
            75% { background-position: 0% 100%; }
            100% { background-position: 0% 50%; }
        }
        
        .container {
            max-width: 800px;
            margin: 0 auto;
            padding-top: 40px;
        }
        
        .header {
            text-align: center;
            margin-bottom: 40px;
            color: white;
            position: relative;
        }
        
        .title {
            font-size: 4rem;
            font-weight: 900;
            margin-bottom: 10px;
            text-shadow: 0 4px 20px rgba(0,0,0,0.3);
            background: linear-gradient(45deg, #fff, #f0f9ff, #dbeafe);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .subtitle {
            font-size: 1.2rem;
            opacity: 0.9;
            font-weight: 400;
        }
        
        .card {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            border-radius: 30px;
            padding: 50px;
            box-shadow: 0 25px 50px rgba(0,0,0,0.1);
            border: 1px solid rgba(255,255,255,0.3);
        }
        
        .upload-area {
            border: 3px dashed #d1d5db;
            border-radius: 20px;
            padding: 60px 20px;
            text-align: center;
            background: linear-gradient(135deg, #f9fafb, #f3f4f6);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            cursor: pointer;
            overflow: hidden;
        }
        
        .upload-area::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(99, 102, 241, 0.1), transparent);
            transition: left 0.6s;
        }
        
        .upload-area:hover::before {
            left: 100%;
        }
        
        .upload-area:hover {
            border-color: #667eea;
            background: linear-gradient(135deg, #f0f4ff, #e0e7ff);
            transform: translateY(-5px);
            box-shadow: 0 15px 35px rgba(102, 126, 234, 0.15);
        }
        
        .upload-area.dragover {
            border-color: #10b981;
            background: linear-gradient(135deg, #ecfdf5, #d1fae5);
            transform: scale(1.02);
        }
        
        .upload-icon {
            font-size: 4rem;
            margin-bottom: 20px;
            animation: bounce 2s infinite;
        }
        
        @keyframes bounce {
            0%, 20%, 50%, 80%, 100% { transform: translateY(0); }
            40% { transform: translateY(-10px); }
            60% { transform: translateY(-5px); }
        }
        
        .upload-text {
            font-size: 1.5rem;
            font-weight: 700;
            color: #374151;
            margin-bottom: 8px;
        }
        
        .upload-subtext {
            color: #6b7280;
            font-size: 1rem;
            margin-bottom: 30px;
        }
        
        input[type="file"] {
            position: absolute;
            width: 100%;
            height: 100%;
            opacity: 0;
            cursor: pointer;
        }
        
        .file-preview {
            display: none;
            background: #667eea;
            color: white;
            padding: 12px 20px;
            border-radius: 15px;
            font-weight: 600;
            margin-top: 15px;
            animation: slideUp 0.3s ease;
        }
        
        @keyframes slideUp {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .convert-btn {
            width: 100%;
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            border: none;
            padding: 18px;
            border-radius: 15px;
            font-size: 1.2rem;
            font-weight: 700;
            cursor: pointer;
            margin-top: 30px;
            transition: all 0.3s ease;
            box-shadow: 0 10px 30px rgba(102, 126, 234, 0.3);
            position: relative;
            overflow: hidden;
        }
        
        .convert-btn::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
            transition: left 0.6s;
        }
        
        .convert-btn:hover::before {
            left: 100%;
        }
        
        .convert-btn:hover {
            transform: translateY(-3px);
            box-shadow: 0 15px 40px rgba(102, 126, 234, 0.4);
        }
        
        .convert-btn:disabled {
            opacity: 0.7;
            cursor: not-allowed;
            transform: none;
        }
        
        .alert {
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid rgba(239, 68, 68, 0.3);
            color: #dc2626;
            padding: 15px 20px;
            border-radius: 15px;
            margin-bottom: 30px;
            font-weight: 600;
        }
        
        .spinner {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 2px solid rgba(255,255,255,0.3);
            border-radius: 50%;
            border-top-color: white;
            animation: spin 1s ease-in-out infinite;
            margin-right: 10px;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        @media (max-width: 640px) {
            .title { font-size: 2.5rem; }
            .card { padding: 30px 20px; }
            .upload-area { padding: 40px 15px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 class="title">SVG Tool by 3DTV</h1>
            <p class="subtitle">Transform images into scalable vector graphics</p>
        </div>
        
        <div class="card">
            {% with messages = get_flashed_messages() %}
                {% if messages %}
                    {% for message in messages %}
                        <div class="alert">⚠️ {{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            
            <form id="uploadForm" action="/upload" method="post" enctype="multipart/form-data">
                <div class="upload-area" id="dropZone" onclick="document.getElementById('fileInput').click()">
                    <div class="upload-icon">📁</div>
                    <div class="upload-text">Drop your image here</div>
                    <div class="upload-subtext">or click to browse • PNG, JPG, GIF, BMP up to 16MB</div>
                    <input type="file" name="file" id="fileInput" accept=".png,.jpg,.jpeg,.bmp,.tiff,.tif,.gif" required>
                    <div class="file-preview" id="filePreview"></div>
                </div>
                
                <button type="submit" class="convert-btn" id="convertBtn">
                    🚀 Convert to SVG
                </button>
            </form>
        </div>
    </div>
    
    <script>
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');
        const filePreview = document.getElementById('filePreview');
        const convertBtn = document.getElementById('convertBtn');
        const form = document.getElementById('uploadForm');
        
        fileInput.addEventListener('change', (e) => {
            if (e.target.files[0]) {
                filePreview.textContent = `📄 ${e.target.files[0].name}`;
                filePreview.style.display = 'block';
            }
        });
        
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });
        
        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('dragover');
        });
        
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            
            const files = e.dataTransfer.files;
            if (files[0]) {
                fileInput.files = files;
                filePreview.textContent = `📄 ${files[0].name}`;
                filePreview.style.display = 'block';
            }
        });
        
        form.addEventListener('submit', () => {
            convertBtn.innerHTML = '<div class="spinner"></div>Converting...';
            convertBtn.disabled = true;
        });
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    debug = os.environ.get('FLASK_ENV') == 'development'
    
    if not find_potrace():
        print("⚠️  WARNING: Potrace not found! Using PIL-based conversion.")
    
    print(f"🚀 SVG Tool by 3DTV starting on port {port}...")
    print(f"🌐 Local: http://127.0.0.1:{port}")
    
    app.run(host='0.0.0.0', port=port, debug=debug)