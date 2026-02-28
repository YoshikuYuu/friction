from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/checktab', methods=['POST'])
def checktab():
    data = request.get_json()
    print(data.get('title'))
    return jsonify({"msg": "Success"})

@app.route('/description', methods=['POST'])
def description():
    data = request.get_json()
    print(data)
    tags = ["placeholder", "values", "for", "possible", "tags"]
    return jsonify({"status": "success", "tags": tags})

@app.route('/tags', methods=['POST'])
def tags():
    data = request.get_json()
    print(data.get('positiveTags'))
    return jsonify({"status": "success"})

if __name__ == '__main__':
    app.run(port=8000, host="0.0.0.0", debug=True)