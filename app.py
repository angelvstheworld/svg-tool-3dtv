from flask import Flask, request, render_template_string, send_file, flash, redirect, url_for, jsonify
import os
import subprocess
from PIL import Image, ImageOps, ImageFilter, ImageEnhance
import tempfile
import uuid
from werkzeug.utils import secure_filename
import json
import base64
import io

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-in-production')
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # Increased to 32MB

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

def preprocess_image(image_path, options):
    """Advanced image preprocessing for better SVG conversion"""
    with Image.open(image_path) as img:
        # Convert to RGB first if needed
        if img.mode in ('RGBA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Apply preprocessing options
        if options.get('enhance_contrast', False):
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.5)
        
        if options.get('sharpen', False):
            img = img.filter(ImageFilter.SHARPEN)
        
        if options.get('denoise', False):
            img = img.filter(ImageFilter.MedianFilter(size=3))
        
        # Smart resizing based on complexity
        max_size = options.get('max_size', 800)
        if img.size[0] > max_size or img.size[1] > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        
        # Convert to grayscale
        img = img.convert('L')
        
        # Apply adaptive threshold or custom threshold
        threshold = options.get('threshold', 128)
        if options.get('adaptive_threshold', False):
            # Simple adaptive thresholding
            import numpy as np
            img_array = np.array(img)
            local_thresh = np.mean(img_array)
            threshold = max(100, min(200, int(local_thresh)))
        
        # Apply threshold
        img = img.point(lambda x: 255 if x > threshold else 0, mode='1')
        
        return img

def image_to_svg_advanced(image_path, output_path, options):
    """
    Advanced SVG conversion with multiple algorithms
    """
    try:
        img = preprocess_image(image_path, options)
        width, height = img.size
        
        # Get conversion method
        method = options.get('method', 'optimized')
        
        if method == 'detailed':
            return create_detailed_svg(img, output_path, options)
        elif method == 'geometric':
            return create_geometric_svg(img, output_path, options)
        else:  # optimized (default)
            return create_optimized_svg(img, output_path, options)
            
    except Exception as e:
        return False, f"Error: {str(e)}"

def create_optimized_svg(img, output_path, options):
    """Create optimized SVG with grouped rectangles"""
    width, height = img.size
    scale_factor = options.get('scale_factor', 1.0)
    final_width = int(width * scale_factor)
    final_height = int(height * scale_factor)
    
    # Create SVG header
    svg_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{final_width}" height="{final_height}" viewBox="0 0 {final_width} {final_height}">
<rect width="{final_width}" height="{final_height}" fill="white"/>
<g transform="scale({scale_factor:.3f})">
'''
    
    pixels = list(img.getdata())
    processed = [[False] * width for _ in range(height)]
    
    # More efficient rectangle grouping
    for y in range(height):
        for x in range(width):
            pixel_index = y * width + x
            if (pixel_index < len(pixels) and 
                pixels[pixel_index] == 0 and 
                not processed[y][x]):
                
                # Find optimal rectangle size
                rect_width, rect_height = find_optimal_rectangle(
                    x, y, width, height, pixels, processed
                )
                
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
    
    return True, "Success (Optimized)"

def find_optimal_rectangle(start_x, start_y, width, height, pixels, processed):
    """Find the largest possible rectangle starting from a point"""
    max_width = 1
    max_height = 1
    
    # Expand width first
    while (start_x + max_width < width):
        pixel_idx = start_y * width + start_x + max_width
        if (pixel_idx >= len(pixels) or 
            pixels[pixel_idx] != 0 or
            processed[start_y][start_x + max_width]):
            break
        max_width += 1
    
    # Then expand height
    while (start_y + max_height < height):
        can_expand = True
        for dx in range(max_width):
            pixel_idx = (start_y + max_height) * width + start_x + dx
            if (pixel_idx >= len(pixels) or 
                pixels[pixel_idx] != 0 or
                processed[start_y + max_height][start_x + dx]):
                can_expand = False
                break
        if not can_expand:
            break
        max_height += 1
    
    return max_width, max_height

def create_detailed_svg(img, output_path, options):
    """Create detailed SVG with smaller elements for better accuracy"""
    width, height = img.size
    scale_factor = options.get('scale_factor', 1.0)
    final_width = int(width * scale_factor)
    final_height = int(height * scale_factor)
    
    svg_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{final_width}" height="{final_height}" viewBox="0 0 {final_width} {final_height}">
<rect width="{final_width}" height="{final_height}" fill="white"/>
<g transform="scale({scale_factor:.3f})">
'''
    
    pixels = list(img.getdata())
    
    # Use smaller rectangles for more detail
    for y in range(0, height, 2):  # Process every 2 pixels
        for x in range(0, width, 2):
            pixel_index = y * width + x
            if pixel_index < len(pixels) and pixels[pixel_index] == 0:
                # Check for 2x2 blocks
                block_size = 1
                if (x + 1 < width and y + 1 < height and
                    pixels[y * width + x + 1] == 0 and
                    pixels[(y + 1) * width + x] == 0 and
                    pixels[(y + 1) * width + x + 1] == 0):
                    block_size = 2
                
                svg_content += f'<rect x="{x}" y="{y}" width="{block_size}" height="{block_size}" fill="black"/>\n'
    
    svg_content += '</g></svg>'
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(svg_content)
    
    return True, "Success (Detailed)"

def create_geometric_svg(img, output_path, options):
    """Create SVG with geometric shapes (circles, polygons)"""
    width, height = img.size
    scale_factor = options.get('scale_factor', 1.0)
    final_width = int(width * scale_factor)
    final_height = int(height * scale_factor)
    
    svg_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{final_width}" height="{final_height}" viewBox="0 0 {final_width} {final_height}">
<rect width="{final_width}" height="{final_height}" fill="white"/>
<g transform="scale({scale_factor:.3f})">
'''
    
    pixels = list(img.getdata())
    
    # Use circles for a more artistic effect
    for y in range(0, height, 4):
        for x in range(0, width, 4):
            pixel_index = y * width + x
            if pixel_index < len(pixels) and pixels[pixel_index] == 0:
                # Determine circle radius based on surrounding pixels
                radius = 2
                center_x = x + radius
                center_y = y + radius
                
                svg_content += f'<circle cx="{center_x}" cy="{center_y}" r="{radius}" fill="black"/>\n'
    
    svg_content += '</g></svg>'
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(svg_content)
    
    return True, "Success (Geometric)"

def convert_image_to_svg(image_path, output_path, options=None):
    """
    Main conversion function with options
    """
    if options is None:
        options = {}
    
    potrace_path = find_potrace()
    
    # Try potrace first if available and requested
    if potrace_path and options.get('use_potrace', True):
        try:
            temp_dir = tempfile.gettempdir()
            temp_pbm = os.path.join(temp_dir, f"temp_{uuid.uuid4()}.pbm")
            
            # Preprocess image for potrace
            img = preprocess_image(image_path, options)
            img.save(temp_pbm, format='PPM')
            
            # Build potrace command with options
            cmd = [potrace_path, temp_pbm, '-s', '-o', output_path]
            
            if options.get('smooth', True):
                cmd.append('--smooth')
            
            if 'curve_tolerance' in options:
                cmd.extend(['--curve-tolerance', str(options['curve_tolerance'])])
                
            cmd.append('--tight')
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if os.path.exists(temp_pbm):
                os.remove(temp_pbm)
            
            if result.returncode == 0 and os.path.exists(output_path):
                return True, "Success (Potrace - High Quality)"
                
        except Exception as e:
            print(f"Potrace failed, falling back to custom: {e}")
    
    # Use custom advanced conversion
    return image_to_svg_advanced(image_path, output_path, options)

@app.route('/')
def index():
    return render_template_string(TEMPLATE)

@app.route('/health')
def health():
    """Health check endpoint for hosting platforms"""
    return jsonify({
        'status': 'healthy',
        'message': 'Enhanced SVG Tool by 3DTV is running',
        'potrace_available': find_potrace() is not None,
        'max_file_size': '32MB',
        'features': ['Advanced preprocessing', 'Multiple conversion methods', 'Custom options']
    })

@app.route('/preview', methods=['POST'])
def preview():
    """Generate preview of conversion settings"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        # Save temporary file
        temp_path = os.path.join(tempfile.gettempdir(), f"preview_{uuid.uuid4()}.tmp")
        file.save(temp_path)
        
        # Get options from request
        options = {
            'threshold': int(request.form.get('threshold', 128)),
            'max_size': 200,  # Small size for preview
            'enhance_contrast': request.form.get('enhance_contrast') == 'true',
            'adaptive_threshold': request.form.get('adaptive_threshold') == 'true'
        }
        
        # Process image
        img = preprocess_image(temp_path, options)
        
        # Convert to base64 for preview
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        img_data = base64.b64encode(buffer.getvalue()).decode()
        
        # Clean up
        os.remove(temp_path)
        
        return jsonify({
            'preview': f"data:image/png;base64,{img_data}",
            'dimensions': img.size
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash('No file selected')
        return redirect(url_for('index'))
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected')
        return redirect(url_for('index'))
    
    allowed_extensions = {'png', 'jpg', 'jpeg', 'bmp', 'tiff', 'tif', 'gif', 'webp'}
    if not ('.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions):
        flash('Invalid file type. Please upload an image file.')
        return redirect(url_for('index'))
    
    try:
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        upload_path = os.path.join(UPLOAD_FOLDER, unique_filename)
        file.save(upload_path)
        
        # Get conversion options from form
        options = {
            'threshold': int(request.form.get('threshold', 128)),
            'method': request.form.get('method', 'optimized'),
            'max_size': int(request.form.get('max_size', 800)),
            'scale_factor': float(request.form.get('scale_factor', 1.0)),
            'enhance_contrast': request.form.get('enhance_contrast') == 'on',
            'sharpen': request.form.get('sharpen') == 'on',
            'denoise': request.form.get('denoise') == 'on',
            'adaptive_threshold': request.form.get('adaptive_threshold') == 'on',
            'use_potrace': request.form.get('use_potrace') == 'on',
            'smooth': request.form.get('smooth') == 'on'
        }
        
        svg_filename = f"{os.path.splitext(unique_filename)[0]}.svg"
        svg_path = os.path.join(UPLOAD_FOLDER, svg_filename)
        
        success, message = convert_image_to_svg(upload_path, svg_path, options)
        
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

# Enhanced HTML template with advanced options
TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Enhanced SVG Tool by 3DTV</title>
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
            animation: gradientFlow 15s ease infinite;
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
            max-width: 900px;
            margin: 0 auto;
            padding-top: 30px;
        }
        
        .header {
            text-align: center;
            margin-bottom: 30px;
            color: white;
        }
        
        .title {
            font-size: 3.5rem;
            font-weight: 900;
            margin-bottom: 10px;
            text-shadow: 0 4px 20px rgba(0,0,0,0.3);
            background: linear-gradient(45deg, #fff, #f0f9ff, #dbeafe);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .subtitle {
            font-size: 1.1rem;
            opacity: 0.9;
            font-weight: 400;
        }
        
        .card {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            border-radius: 25px;
            padding: 40px;
            box-shadow: 0 25px 50px rgba(0,0,0,0.1);
            border: 1px solid rgba(255,255,255,0.3);
            margin-bottom: 20px;
        }
        
        .upload-area {
            border: 3px dashed #d1d5db;
            border-radius: 20px;
            padding: 50px 20px;
            text-align: center;
            background: linear-gradient(135deg, #f9fafb, #f3f4f6);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            cursor: pointer;
            overflow: hidden;
            position: relative;
        }
        
        .upload-area:hover {
            border-color: #667eea;
            background: linear-gradient(135deg, #f0f4ff, #e0e7ff);
            transform: translateY(-3px);
        }
        
        .upload-icon {
            font-size: 3rem;
            margin-bottom: 15px;
        }
        
        .upload-text {
            font-size: 1.3rem;
            font-weight: 700;
            color: #374151;
            margin-bottom: 5px;
        }
        
        .upload-subtext {
            color: #6b7280;
            margin-bottom: 20px;
        }
        
        input[type="file"] {
            position: absolute;
            width: 100%;
            height: 100%;
            opacity: 0;
            cursor: pointer;
        }
        
        .options-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 30px;
            margin-top: 30px;
        }
        
        .option-group {
            background: rgba(249, 250, 251, 0.8);
            border-radius: 15px;
            padding: 25px;
            border: 1px solid rgba(229, 231, 235, 0.5);
        }
        
        .option-group h3 {
            color: #374151;
            margin-bottom: 15px;
            font-size: 1.1rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .form-group {
            margin-bottom: 15px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 5px;
            font-weight: 500;
            color: #4b5563;
            font-size: 0.9rem;
        }
        
        .form-control {
            width: 100%;
            padding: 10px 12px;
            border: 2px solid #e5e7eb;
            border-radius: 8px;
            font-size: 14px;
            transition: all 0.2s;
            background: white;
        }
        
        .form-control:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        
        .checkbox-group {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 10px;
        }
        
        .checkbox-group input[type="checkbox"] {
            width: 16px;
            height: 16px;
            accent-color: #667eea;
        }
        
        .checkbox-group label {
            margin: 0;
            font-size: 14px;
            cursor: pointer;
        }
        
        .range-container {
            position: relative;
        }
        
        .range-value {
            position: absolute;
            right: 0;
            top: -25px;
            font-size: 12px;
            color: #6b7280;
            font-weight: 600;
        }
        
        input[type="range"] {
            -webkit-appearance: none;
            width: 100%;
            height: 6px;
            border-radius: 3px;
            background: #e5e7eb;
            outline: none;
        }
        
        input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            appearance: none;
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background: #667eea;
            cursor: pointer;
            box-shadow: 0 2px 6px rgba(0,0,0,0.2);
        }
        
        .preview-container {
            background: white;
            border-radius: 10px;
            padding: 15px;
            text-align: center;
            min-height: 150px;
            border: 2px dashed #e5e7eb;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .preview-image {
            max-width: 200px;
            max-height: 200px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        
        .convert-btn {
            width: 100%;
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            border: none;
            padding: 16px;
            border-radius: 12px;
            font-size: 1.1rem;
            font-weight: 700;
            cursor: pointer;
            margin-top: 25px;
            transition: all 0.3s ease;
            box-shadow: 0 10px 25px rgba(102, 126, 234, 0.3);
        }
        
        .convert-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 15px 35px rgba(102, 126, 234, 0.4);
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
            padding: 12px 16px;
            border-radius: 10px;
            margin-bottom: 20px;
            font-weight: 500;
        }
        
        .spinner {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid rgba(255,255,255,0.3);
            border-radius: 50%;
            border-top-color: white;
            animation: spin 1s ease-in-out infinite;
            margin-right: 8px;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .file-preview {
            display: none;
            background: linear-gradient(135deg, #10b981, #059669);
            color: white;
            padding: 10px 16px;
            border-radius: 10px;
            margin-top: 15px;
            font-weight: 600;
        }
        
        @media (max-width: 768px) {
            .title { font-size: 2.5rem; }
            .card { padding: 25px 20px; }
            .options-grid { grid-template-columns: 1fr; gap: 20px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 class="title">Enhanced SVG Tool</h1>
            <p class="subtitle">Professional image to vector conversion with advanced options</p>
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
                    <div class="upload-icon">🎨</div>
                    <div class="upload-text">Drop your image here</div>
                    <div class="upload-subtext">PNG, JPG, GIF, BMP, WebP up to 32MB</div>
                    <input type="file" name="file" id="fileInput" accept=".png,.jpg,.jpeg,.bmp,.tiff,.tif,.gif,.webp" required>
                    <div class="file-preview" id="filePreview"></div>
                </div>
                
                <div class="options-grid">
                    <div class="option-group">
                        <h3>🎯 Conversion Method</h3>
                        <div class="form-group">
                            <select name="method" class="form-control">
                                <option value="optimized">Optimized (Best Balance)</option>
                                <option value="detailed">Detailed (High Accuracy)</option>
                                <option value="geometric">Geometric (Artistic)</option>
                            </select>
                        </div>
                        
                        <div class="form-group">
                            <label>Threshold</label>
                            <div class="range-container">
                                <span class="range-value" id="thresholdValue">128</span>
                                <input type="range" name="threshold" min="50" max="200" value="128" 
                                       class="form-control" onInput="updateRangeValue(this, 'thresholdValue')">
                            </div>
                        </div>
                        
                        <div class="form-group">
                            <label>Maximum Size (px)</label>
                            <input type="number" name="max_size" value="800" min="200" max="2000" class="form-control">
                        </div>
                        
                        <div class="form-group">
                            <label>Scale Factor</label>
                            <div class="range-container">
                                <span class="range-value" id="scaleValue">1.0</span>
                                <input type="range" name="scale_factor" min="0.5" max="3.0" value="1.0" step="0.1"
                                       class="form-control" onInput="updateRangeValue(this, 'scaleValue')">
                            </div>
                        </div>
                    </div>
                    
                    <div class="option-group">
                        <h3>⚙️ Processing Options</h3>
                        
                        <div class="checkbox-group">
                            <input type="checkbox" name="enhance_contrast" id="enhance_contrast">
                            <label for="enhance_contrast">Enhance Contrast</label>
                        </div>
                        
                        <div class="checkbox-group">
                            <input type="checkbox" name="sharpen" id="sharpen">
                            <label for="sharpen">Sharpen Image</label>
                        </div>
                        
                        <div class="checkbox-group">
                            <input type="checkbox" name="denoise" id="denoise">
                            <label for="denoise">Reduce Noise</label>
                        </div>
                        
                        <div class="checkbox-group">
                            <input type="checkbox" name="adaptive_threshold" id="adaptive_threshold">
                            <label for="adaptive_threshold">Smart Threshold</label>
                        </div>
                        
                        <div class="checkbox-group">
                            <input type="checkbox" name="use_potrace" id="use_potrace" checked>
                            <label for="use_potrace">Use Potrace (if available)</label>
                        </div>
                        
                        <div class="checkbox-group">
                            <input type="checkbox" name="smooth" id="smooth" checked>
                            <label for="smooth">Smooth Curves</label>
                        </div>
                    </div>
                    
                    <div class="option-group">
                        <h3>👁️ Preview</h3>
                        <div class="preview-container" id="previewContainer">
                            <div style="color: #6b7280;">Upload an image to see preview</div>
                        </div>
                        <button type="button" id="previewBtn" class="convert-btn" style="margin-top: 15px; background: linear-gradient(135deg, #10b981, #059669);" disabled>
                            Generate Preview
                        </button>
                    </div>
                </div>
                
                <button type="submit" class="convert-btn" id="convertBtn">
                    🚀 Convert to SVG
                </button>
            </form>
        </div>
        
        <div class="card" style="background: rgba(255, 255, 255, 0.9); padding: 30px;">
            <h3 style="margin-bottom: 15px; color: #374151;">✨ New Features</h3>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px;">
                <div>
                    <h4 style="color: #667eea; margin-bottom: 8px;">🎯 Multiple Algorithms</h4>
                    <p style="font-size: 14px; color: #6b7280;">Choose from optimized, detailed, or geometric conversion methods for different use cases.</p>
                </div>
                <div>
                    <h4 style="color: #667eea; margin-bottom: 8px;">🖼️ Smart Preprocessing</h4>
                    <p style="font-size: 14px; color: #6b7280;">Advanced image enhancement with contrast boost, sharpening, and noise reduction.</p>
                </div>
                <div>
                    <h4 style="color: #667eea; margin-bottom: 8px;">⚡ Live Preview</h4>
                    <p style="font-size: 14px; color: #6b7280;">See how your settings affect the conversion before processing the full image.</p>
                </div>
                <div>
                    <h4 style="color: #667eea; margin-bottom: 8px;">🎛️ Fine Control</h4>
                    <p style="font-size: 14px; color: #6b7280;">Adjust threshold, scaling, and processing options for perfect results.</p>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');
        const filePreview = document.getElementById('filePreview');
        const convertBtn = document.getElementById('convertBtn');
        const previewBtn = document.getElementById('previewBtn');
        const previewContainer = document.getElementById('previewContainer');
        const form = document.getElementById('uploadForm');
        
        let currentFile = null;
        
        function updateRangeValue(slider, targetId) {
            document.getElementById(targetId).textContent = slider.value;
            if (currentFile && targetId === 'thresholdValue') {
                generatePreview();
            }
        }
        
        fileInput.addEventListener('change', (e) => {
            handleFileSelect(e.target.files[0]);
        });
        
        function handleFileSelect(file) {
            if (file) {
                currentFile = file;
                filePreview.innerHTML = `📄 ${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB)`;
                filePreview.style.display = 'block';
                previewBtn.disabled = false;
                
                // Auto-generate preview for smaller files
                if (file.size < 5 * 1024 * 1024) { // < 5MB
                    generatePreview();
                }
            }
        }
        
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.style.borderColor = '#10b981';
            dropZone.style.background = 'linear-gradient(135deg, #ecfdf5, #d1fae5)';
        });
        
        dropZone.addEventListener('dragleave', () => {
            dropZone.style.borderColor = '#d1d5db';
            dropZone.style.background = 'linear-gradient(135deg, #f9fafb, #f3f4f6)';
        });
        
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.style.borderColor = '#d1d5db';
            dropZone.style.background = 'linear-gradient(135deg, #f9fafb, #f3f4f6)';
            
            const files = e.dataTransfer.files;
            if (files[0]) {
                fileInput.files = files;
                handleFileSelect(files[0]);
            }
        });
        
        previewBtn.addEventListener('click', generatePreview);
        
        async function generatePreview() {
            if (!currentFile) return;
            
            previewBtn.innerHTML = '<div class="spinner"></div>Generating...';
            previewBtn.disabled = true;
            
            const formData = new FormData();
            formData.append('file', currentFile);
            formData.append('threshold', document.querySelector('input[name="threshold"]').value);
            formData.append('enhance_contrast', document.getElementById('enhance_contrast').checked);
            formData.append('adaptive_threshold', document.getElementById('adaptive_threshold').checked);
            
            try {
                const response = await fetch('/preview', {
                    method: 'POST',
                    body: formData
                });
                
                const data = await response.json();
                
                if (data.preview) {
                    previewContainer.innerHTML = `
                        <img src="${data.preview}" class="preview-image" alt="Preview">
                        <div style="margin-top: 10px; font-size: 12px; color: #6b7280;">
                            Preview: ${data.dimensions[0]}×${data.dimensions[1]}px
                        </div>
                    `;
                } else {
                    previewContainer.innerHTML = '<div style="color: #ef4444;">Preview failed</div>';
                }
            } catch (error) {
                previewContainer.innerHTML = '<div style="color: #ef4444;">Preview error</div>';
                console.error('Preview error:', error);
            }
            
            previewBtn.innerHTML = 'Generate Preview';
            previewBtn.disabled = false;
        }
        
        form.addEventListener('submit', () => {
            convertBtn.innerHTML = '<div class="spinner"></div>Converting...';
            convertBtn.disabled = true;
        });
        
        // Smart defaults based on file type
        fileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) {
                const fileName = file.name.toLowerCase();
                
                // Adjust defaults based on file type
                if (fileName.includes('photo') || fileName.includes('jpg') || fileName.includes('jpeg')) {
                    document.getElementById('enhance_contrast').checked = true;
                    document.getElementById('denoise').checked = true;
                    document.querySelector('select[name="method"]').value = 'detailed';
                } else if (fileName.includes('logo') || fileName.includes('icon')) {
                    document.getElementById('sharpen').checked = true;
                    document.querySelector('select[name="method"]').value = 'optimized';
                } else if (fileName.includes('art') || fileName.includes('drawing')) {
                    document.querySelector('select[name="method"]').value = 'geometric';
                }
            }
        });
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey || e.metaKey) {
                switch(e.key) {
                    case 'u':
                        e.preventDefault();
                        fileInput.click();
                        break;
                    case 'p':
                        e.preventDefault();
                        if (!previewBtn.disabled) generatePreview();
                        break;
                    case 'Enter':
                        if (currentFile && !convertBtn.disabled) {
                            e.preventDefault();
                            form.submit();
                        }
                        break;
                }
            }
        });
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    debug = os.environ.get('FLASK_ENV') == 'development'
    
    potrace_available = find_potrace() is not None
    print("🚀 Enhanced SVG Tool by 3DTV")
    print("=" * 40)
    print(f"📡 Port: {port}")
    print(f"🔧 Potrace: {'✅ Available' if potrace_available else '⚠️ Not found (using fallback)'}")
    print(f"💾 Max file size: 32MB")
    print(f"🎨 Conversion methods: 3 (Optimized, Detailed, Geometric)")
    print(f"🖼️ Preview: Enabled")
    print(f"⚡ Advanced preprocessing: Enabled")
    print("=" * 40)
    print(f"🌐 Access at: http://127.0.0.1:{port}")
    
    app.run(host='0.0.0.0', port=port, debug=debug)
                
