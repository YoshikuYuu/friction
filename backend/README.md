# Setup

Copy .env.example and add your Gemini API key.
```bash
cp .env.example .env
```

Create a virtual environment and install required packages.

```bash
# If you have uv
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
# Otherwise
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
