import os
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.getcwd(), ".env"))
from huggingface_hub import HfApi
api = HfApi(token=os.getenv("HF_TOKEN"))
repo = os.getenv("HF_ASSET_SUMMARIZATION_REPO")
print("Uploading onnx_asset_summary_final ->", repo, flush=True)
api.upload_folder(
    folder_path="onnx_asset_summary_final",
    repo_id=repo,
    repo_type="model",
    ignore_patterns=["*.zip", "*.log", "__pycache__*", ".git*"],
    commit_message="Add ONNX (encoder + merged decoder) for optimum/onnxruntime inference",
)
print("ASSET UPLOAD OK ->", repo)
