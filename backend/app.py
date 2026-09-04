import os
import sys
from flask import Flask, send_from_directory
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(__file__))

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)

from routes.trips import trips_bp
from routes.ai import ai_bp
app.register_blueprint(trips_bp)
app.register_blueprint(ai_bp)


@app.route("/")
def serve_index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:path>")
def serve_static(path):
    file_path = os.path.join(app.static_folder, path)
    if os.path.isfile(file_path):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
