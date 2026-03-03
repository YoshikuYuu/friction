from flask import Flask, jsonify, request
from flask_cors import CORS
from sentence_transformers import SentenceTransformer
import torch
import threading
import time
import json
from pathlib import Path
import re
import importlib
from typing import Any

from category import CategoryConfig, BLOCKMODE_STRICT, BLOCKMODE_WARN
from config_store import ConfigStore, LISTTYPE_ALLOW, LISTTYPE_BLOCK
import voice
from gemini import ExampleGenerator
from utils import decompose_url

CategoryClassifier = importlib.import_module("categoryclassifier").CategoryClassifier

app = Flask(__name__)
CORS(app)

embedder = SentenceTransformer("Snowflake/snowflake-arctic-embed-xs")
example_generator = ExampleGenerator()

def embedding_fn(texts: list[str], query: bool) -> torch.Tensor:
    if query:
        return torch.as_tensor(embedder.encode(texts, prompt="query"), dtype=torch.float32)
    return torch.as_tensor(embedder.encode(texts), dtype=torch.float32)

configs: dict[str, CategoryConfig] = {}
blocklist_strict: dict[str, Any] = {}
blocklist_warn: dict[str, Any] = {}
allowlist_strict: dict[str, Any] = {}
allowlist_warn: dict[str, Any] = {}

store = ConfigStore(Path(__file__).parent / "data" / "categories.json")
PROBE_ROOT_DIR = Path(__file__).parent / "data" / "probes"
DEFAULT_MASCOT_LINES = {
    "warn": "Hey. Are you supposed to be on this page?",
    "strict": "You blocked this page for a reason. Lock back in, nerd.",
}
mascot_lines_by_category: dict[str, dict[str, str]] = {}


def _bucket_for(list_type: str, block_mode: str) -> dict[str, Any]:
    if list_type == LISTTYPE_ALLOW and block_mode == BLOCKMODE_STRICT:
        return allowlist_strict
    if list_type == LISTTYPE_ALLOW and block_mode == BLOCKMODE_WARN:
        return allowlist_warn
    if list_type == LISTTYPE_BLOCK and block_mode == BLOCKMODE_WARN:
        return blocklist_warn
    return blocklist_strict


def _config_to_record(cfg: CategoryConfig, list_type: str, mascot_lines: dict[str, str] | None = None) -> dict:
    return {
        "name": cfg.name,
        "initial_definition": cfg.initial_definition,
        "positive_definitions": cfg.positive_definitions,
        "negative_definitions": cfg.negative_definitions,
        "blockMode": cfg.block_mode,
        "listType": list_type,
        "mascotLines": mascot_lines or mascot_lines_by_category.get(cfg.name, DEFAULT_MASCOT_LINES),
    }


def _slugify_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned or "untitled"


def _probe_dir(name: str, list_type: str, block_mode: str) -> Path:
    folder = f"{_slugify_name(name)}__{list_type}__{block_mode}"
    return PROBE_ROOT_DIR / folder


def _write_probe_dataset_json(
    cfg: CategoryConfig,
    list_type: str,
    dataset: dict[str, list[str]],
) -> Path:
    save_dir = _probe_dir(name=cfg.name, list_type=list_type, block_mode=cfg.block_mode)
    save_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = save_dir / "dataset.json"
    payload = {
        "name": cfg.name,
        "listType": list_type,
        "blockMode": cfg.block_mode,
        "initialDefinition": cfg.initial_definition,
        "positive": dataset.get("positive", []),
        "negative": dataset.get("negative", []),
    }
    dataset_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return dataset_path


def _train_and_attach_classifier(
    cfg: CategoryConfig,
    list_type: str,
    epochs: int = 8,
) -> tuple[Any, dict]:
    dataset = example_generator.generate_probe_dataset(cfg, n=200)
    dataset_path = _write_probe_dataset_json(cfg=cfg, list_type=list_type, dataset=dataset)
    classifier = CategoryClassifier(cfg=cfg, embed_fn=embedding_fn)
    train_result = classifier.train_probe(
        positive_texts=dataset["positive"],
        negative_texts=dataset["negative"],
        epochs=epochs,
    )
    save_dir = _probe_dir(name=cfg.name, list_type=list_type, block_mode=cfg.block_mode)
    classifier.save(save_dir)

    _bucket_for(list_type, cfg.block_mode)[cfg.name] = classifier
    configs[cfg.name] = cfg

    metrics = {
        "epochs": train_result.epochs,
        "samples": train_result.samples,
        "finalLoss": train_result.final_loss,
        "probeDir": str(save_dir),
        "datasetPath": str(dataset_path),
    }
    return classifier, metrics


def _rebuild_runtime_from_store() -> None:
    configs.clear()
    blocklist_strict.clear()
    blocklist_warn.clear()
    allowlist_strict.clear()
    allowlist_warn.clear()
    mascot_lines_by_category.clear()

    for list_type, block_mode, record in store.iter_records():
        name = record["name"]
        initial_definition = record["initial_definition"]
        cfg = CategoryConfig(name=name, initial_definition=initial_definition, block_mode=block_mode)
        cfg.positive_definitions = record["positive_definitions"]
        cfg.negative_definitions = record["negative_definitions"]
        mascot_lines_by_category[name] = record.get("mascotLines", DEFAULT_MASCOT_LINES)

        configs[name] = cfg
        classifier = CategoryClassifier(cfg=cfg, embed_fn=embedding_fn)
        probe_dir = _probe_dir(name=name, list_type=list_type, block_mode=block_mode)
        if probe_dir.exists():
            try:
                classifier.load(probe_dir)
            except Exception as exc:
                print(f"Failed loading probe for category '{name}': {exc}")
        else:
            try:
                print(f"Probe missing for category '{name}'. Training a new probe...")
                dataset = example_generator.generate_probe_dataset(cfg, n=200)
                _write_probe_dataset_json(cfg=cfg, list_type=list_type, dataset=dataset)
                classifier.train_probe(
                    positive_texts=dataset["positive"],
                    negative_texts=dataset["negative"],
                    epochs=8,
                )
                classifier.save(probe_dir)
            except Exception as exc:
                print(f"Failed training startup probe for category '{name}': {exc}")
        _bucket_for(list_type, block_mode)[name] = classifier

_rebuild_runtime_from_store()

def _parse_checktab_payload(data):
    if isinstance(data, dict):
        url, title = data.get("url", ""), data.get("title", "")
        if not url and not title:
            raise ValueError("Checktab payload must include at least 'url' or 'title' field.")
        return {
            "url": url.strip(),
            "title": title.strip(),
        }
    raise ValueError("Payload must be a JSON object.")
        
def _parse_description_payload(data):
    if isinstance(data, dict):
        name, desc, block_mode = data.get("name"), data.get("desc"), data.get("blockMode")
        if not name or not desc or not block_mode:
            raise ValueError("Description payload must include 'name', 'desc', and 'blockMode' fields.")
        if block_mode.strip() not in {BLOCKMODE_STRICT, BLOCKMODE_WARN}:
            raise ValueError(f"Invalid block mode: {block_mode}. Must be '{BLOCKMODE_STRICT}' or '{BLOCKMODE_WARN}'.")
        return {
            "name": name.strip(),
            "description": desc.strip(),
            "blockMode": block_mode.strip(),
            "listType": LISTTYPE_BLOCK, # TODO: allow this to be specified in the future if we add allowlist support in the UI
        }
    raise ValueError("Payload must be a JSON object.")

def _parse_tags_payload(data):
    if isinstance(data, dict):
        name, pos, neg = data.get("name"), data.get("positiveTags", []), data.get("negativeTags", [])
        if not name:
            raise ValueError("Tags payload must include non-empty 'name' field.")
        if not isinstance(pos, list) or not isinstance(neg, list):
            raise ValueError("'positiveTags' and 'negativeTags' fields must be lists.")
        return {
            "name": name.strip(),
            "positiveTags": pos,
            "negativeTags": neg,
        }
    raise ValueError("Payload must be a JSON object.")

@app.route('/home', methods=['POST'])
def home():
    voice.play_home_welcome()
    return jsonify({"status": "success"})


@app.route('/checktab', methods=['POST'])
def checktab():
    data = request.get_json(silent=True)
    try:
        payload = _parse_checktab_payload(data)
        url, title = payload["url"], payload["title"]
    except Exception as e:
        print(f"Error parsing checktab payload: {e}")
        return jsonify({"status": "error", "msg": "Invalid payload format."}), 400

    url_text = " ".join(word for word in decompose_url(url) if word)
    candidate_text = f"{title} {url_text}".strip()

    if not candidate_text:
        return jsonify({"status": "error", "msg": "Missing tab content."}), 400

    matched = None
    classifier_outputs: list[dict[str, Any]] = []

    # TODO: consider allowlist categories as well, and how they should interact with blocklist categories if there's overlap or conflictd

    # iterate through strict blocklist first, then warn blocklist so that if
    # candidate matches any strict category, we can break early
    blocklist = list(blocklist_strict.values()) + list(blocklist_warn.values())
    print(f"[checktab] candidate_text='{candidate_text}' active_classifiers={len(blocklist)}")
    for classifier in blocklist:
        score = classifier.score_text(candidate_text)
        threshold = getattr(classifier, "decision_threshold", 0.5)
        is_match = classifier.matches(candidate_text)

        classifier_outputs.append(
            {
                "name": classifier.config.name,
                "blockMode": classifier.config.block_mode,
                "score": round(score, 4),
                "threshold": round(float(threshold), 4),
                "matched": bool(is_match),
            }
        )
        print(
            f"[checktab] classifier='{classifier.config.name}' mode='{classifier.config.block_mode}' "
            f"score={score:.4f} threshold={float(threshold):.4f} matched={is_match}"
        )

        if is_match and matched is None:
            matched = classifier.config

    print(f"[checktab] outputs={classifier_outputs}")

    if matched:
        msg = f"Matched category: {matched.name}"
        block_mode = matched.block_mode
    else:
        msg = "No category match found."
        block_mode = "none"

    if block_mode == "warn":
        threading.Thread(target=warn_audio, args=(matched.name if matched else None,), daemon=True).start()
    if block_mode == "strict":
        threading.Thread(target=strict_audio, args=(matched.name if matched else None,), daemon=True).start()

    return jsonify(
        {
            "status": "success",
            "msg": msg,
            "matched": bool(matched),
            "blockMode": block_mode,
            # "blockMode": "warn",
        }
    )

def strict_audio(category_name: str | None = None):
    line = DEFAULT_MASCOT_LINES["strict"]
    if category_name:
        line = mascot_lines_by_category.get(category_name, DEFAULT_MASCOT_LINES).get("strict", line)
    voice.speak(line)

def warn_audio(category_name: str | None = None):
    time.sleep(0.3)  # only blocks this thread

    line = DEFAULT_MASCOT_LINES["warn"]
    if category_name:
        line = mascot_lines_by_category.get(category_name, DEFAULT_MASCOT_LINES).get("warn", line)

    voice.speak(line)

@app.route('/description', methods=['POST'])
def description():
    data = request.get_json(silent=True)
    try:
        payload = _parse_description_payload(data)
        desc, name, block_mode, list_type = payload["description"], payload["name"], payload["blockMode"], payload["listType"]
    except Exception as e:
        print(f"Error parsing description payload: {e}")
        return jsonify({"status": "error", "msg": "Invalid payload format."}), 400

    cfg = CategoryConfig(name=name, initial_definition=desc, block_mode=block_mode)
    configs[cfg.name] = cfg

    list_type = LISTTYPE_BLOCK
    mascot_lines_by_category[cfg.name] = DEFAULT_MASCOT_LINES.copy()

    store.upsert_record(
        name=cfg.name,
        list_type=list_type,
        block_mode=cfg.block_mode,
        record=_config_to_record(
            cfg,
            list_type=list_type,
            mascot_lines=mascot_lines_by_category[cfg.name],
        ),
    )

    tags: list[str] = []
    try:
        tags = example_generator.generate_examples(desc)
    except Exception as exc:
        print(f"Error generating edge-case tags: {exc}")
        return jsonify({"status": "error", "msg": "Failed to generate edge-case tags."}), 500

    return jsonify({
        "status": "success",
        "msg": f"CategoryConfig initialized for {name} in {list_type} with block mode {block_mode}.",
        "categoryName": name,
        "tags": tags,
    })

@app.route('/tags', methods=['POST'])
def tags():
    data = request.get_json(silent=True)
    try:
        payload = _parse_tags_payload(data)
        name, positive_tags, negative_tags = payload["name"], payload["positiveTags"], payload["negativeTags"]
    except Exception as e:
        print(f"Error parsing tags payload: {e}")
        return jsonify({"status": "error", "msg": "Invalid payload format."}), 400
    
    # TODO: add ability to add categories to allowlist

    try:
        cfg = configs[name]
    except KeyError:
        return jsonify({"status": "error", "msg": f"No category config found for name: {name}"}), 404

    list_type = LISTTYPE_BLOCK # TODO: allow this to be specified in the future

    cfg.update_definitions(positive=positive_tags, negative=negative_tags)

    try:
        _, probe_metrics = _train_and_attach_classifier(cfg=cfg, list_type=list_type, epochs=8)
    except Exception as exc:
        print(f"Error retraining probe for category '{name}': {exc}")
        return jsonify({"status": "error", "msg": "Failed to retrain category probe."}), 500

    try:
        mascot_lines = example_generator.generate_mascot_lines(cfg)
    except Exception as exc:
        print(f"Error generating mascot lines for category '{name}': {exc}")
        mascot_lines = DEFAULT_MASCOT_LINES.copy()

    mascot_lines_by_category[cfg.name] = mascot_lines

    store.upsert_record(
        name=cfg.name,
        list_type=list_type,
        block_mode=cfg.block_mode,
        record=_config_to_record(cfg, list_type=list_type, mascot_lines=mascot_lines),
    )

    return jsonify(
        {
            "status": "success",
            "msg": "Category tags saved.",
            "categoryName": cfg.name,
            "positiveCount": len(cfg.positive_definitions),
            "negativeCount": len(cfg.negative_definitions),
            "probeTraining": probe_metrics,
            "mascotLines": mascot_lines,
        }
    )


@app.route('/configs', methods=['GET'])
def get_configs():
    return jsonify({"status": "success", "configs": store.configs_as_list()})


@app.route('/config', methods=['DELETE'])
def delete_config():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    list_type = (data.get("listType") or "").strip()
    block_mode = (data.get("blockMode") or "").strip()

    if not name:
        return jsonify({"status": "error", "msg": "Missing category name."}), 400
    if block_mode not in {BLOCKMODE_STRICT, BLOCKMODE_WARN}:
        return jsonify({"status": "error", "msg": "Invalid blockMode."}), 400
    if list_type not in {LISTTYPE_BLOCK, LISTTYPE_ALLOW}:
        return jsonify({"status": "error", "msg": "Invalid listType."}), 400

    deleted = store.delete_record(name=name, list_type=list_type, block_mode=block_mode)
    if not deleted:
        return jsonify({"status": "error", "msg": "Category not found."}), 404

    probe_dir = _probe_dir(name=name, list_type=list_type, block_mode=block_mode)
    if probe_dir.exists():
        for child in probe_dir.iterdir():
            if child.is_file():
                child.unlink()
        probe_dir.rmdir()

    _rebuild_runtime_from_store()
    return jsonify({"status": "success", "msg": "Category removed."})

if __name__ == '__main__':
    # play(audio)
    app.run(port=8000, host="0.0.0.0", debug=True)
