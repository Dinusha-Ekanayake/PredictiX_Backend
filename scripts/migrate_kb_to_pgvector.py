from sqlalchemy.orm import Session
from sentence_transformers import SentenceTransformer
from app.db.session import SessionLocal
from app.models import KBDocument
from app.kb.kb_documents import KB_DOCUMENTS

def main():
    print("Loading embedding model...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    
    print("Connecting to DB...")
    db = SessionLocal()
    
    try:
        print(f"Migrating {len(KB_DOCUMENTS)} documents...")
        for doc in KB_DOCUMENTS:
            # Check if exists
            existing = db.query(KBDocument).filter(KBDocument.id == doc["id"]).first()
            if existing:
                print(f"Skipping {doc['id']} (already exists)")
                continue
                
            text = doc["text"]
            embedding = model.encode(text).tolist()
            
            kb_doc = KBDocument(
                id=doc["id"],
                text=text,
                tags=doc.get("tags", []),
                embedding=embedding
            )
            db.add(kb_doc)
            
        db.commit()
        print("Migration complete!")
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()
