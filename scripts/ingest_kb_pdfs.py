import os
import re
import hashlib
from typing import List, Dict
from sqlalchemy.orm import Session
from sentence_transformers import SentenceTransformer
from pypdf import PdfReader
from tqdm import tqdm

from app.db.session import SessionLocal
from app.models import KBDocument

PDF_DIR = r"D:\Project\KB resources"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

def clean_text(text: str) -> str:
    """Basic text cleaning to remove excessive whitespace and noisy artifacts."""
    if not text:
        return ""
    # Replace multiple whitespaces and newlines with a single space
    text = re.sub(r'\s+', ' ', text)
    # Remove null bytes
    text = text.replace('\x00', '')
    return text.strip()

def chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Custom sliding-window chunking algorithm."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        
        # If this isn't the very last chunk, try to break at a clean boundary (period or space)
        if end < len(text):
            # Try to find the last period or space within the last 100 chars of the chunk
            boundary_search_zone = chunk[-100:]
            last_period = boundary_search_zone.rfind('.')
            if last_period != -1:
                end = start + chunk_size - 100 + last_period + 1
                chunk = text[start:end]
            else:
                last_space = boundary_search_zone.rfind(' ')
                if last_space != -1:
                    end = start + chunk_size - 100 + last_space
                    chunk = text[start:end]

        if len(chunk.strip()) > 50: # Ignore very small fragments
            chunks.append(chunk.strip())
            
        start = end - overlap
        
        # Prevent infinite loop if we somehow can't advance
        if start >= end:
            start += chunk_size
            
    return chunks

def generate_id(text: str, filename: str) -> str:
    """Generate a deterministic ID based on the chunk content to prevent duplicates."""
    hash_object = hashlib.md5((filename + text).encode('utf-8'))
    return f"pdf_{hash_object.hexdigest()}"

def main():
    print(f"Scanning directory: {PDF_DIR}")
    pdf_files = [f for f in os.listdir(PDF_DIR) if f.lower().endswith('.pdf')]
    print(f"Found {len(pdf_files)} PDF files.")
    
    if not pdf_files:
        print("No PDFs found. Exiting.")
        return

    print("Loading SentenceTransformer model (all-MiniLM-L6-v2)...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    
    print("Connecting to Vector Database...")
    db = SessionLocal()
    
    total_chunks_inserted = 0
    total_chunks_skipped = 0
    
    try:
        for filename in pdf_files:
            filepath = os.path.join(PDF_DIR, filename)
            print(f"\nProcessing: {filename}")
            
            try:
                reader = PdfReader(filepath)
                full_text = ""
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        full_text += text + "\n"
                        
                cleaned_text = clean_text(full_text)
                if not cleaned_text:
                    print(f"  No extractable text found in {filename}.")
                    continue
                    
                chunks = chunk_text(cleaned_text, CHUNK_SIZE, CHUNK_OVERLAP)
                print(f"  Generated {len(chunks)} chunks.")
                
                # Batch encode all chunks for this file
                embeddings = model.encode(chunks, show_progress_bar=True)
                
                # Deduplicate chunks in memory first
                seen_ids = set()
                unique_chunks = []
                unique_embeddings = []
                for chunk_text_content, embedding in zip(chunks, embeddings):
                    chunk_id = generate_id(chunk_text_content, filename)
                    if chunk_id not in seen_ids:
                        seen_ids.add(chunk_id)
                        unique_chunks.append((chunk_id, chunk_text_content))
                        unique_embeddings.append(embedding)

                inserted = 0
                skipped = 0
                
                for (chunk_id, chunk_text_content), embedding in zip(unique_chunks, unique_embeddings):
                    
                    # Check idempotency in DB
                    existing = db.query(KBDocument).filter(KBDocument.id == chunk_id).first()
                    if existing:
                        skipped += 1
                        continue
                        
                    kb_doc = KBDocument(
                        id=chunk_id,
                        text=chunk_text_content,
                        tags=["pdf", filename],
                        embedding=embedding.tolist()
                    )
                    db.add(kb_doc)
                    inserted += 1
                
                db.commit()
                print(f"  Inserted: {inserted} | Skipped (Duplicates): {skipped}")
                total_chunks_inserted += inserted
                total_chunks_skipped += skipped
                
            except Exception as e:
                db.rollback()
                err_msg = str(e).encode('ascii', 'replace').decode('ascii')
                print(f"  Error processing {filename}: {type(e).__name__} - {err_msg}")
                
        print("\n" + "="*50)
        print("PDF INGESTION COMPLETE")
        print(f"Total New Chunks Inserted: {total_chunks_inserted}")
        print(f"Total Chunks Skipped (Already Existed): {total_chunks_skipped}")
        print("="*50)
        
    finally:
        db.close()

if __name__ == "__main__":
    main()
